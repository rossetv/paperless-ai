"""Search-core orchestration — the bounded agentic pipeline (spec §6.3).

``SearchCore`` is the single entry point to the read-side search pipeline.  It
wires the planner, retriever, and synthesiser into the hard-bounded loop of
spec §6.3 and assembles the public :class:`~search.models.SearchResult`.

Two public methods, both pure-library (no FastAPI, no MCP — CODE_GUIDELINES
§2.5):

- ``answer(query, ui_filters)`` — the full pipeline: plan, retrieve, an
  optional single refinement, and synthesis.  Used by the HTTP ``/api/search``
  endpoint and the MCP ``ask_documents`` tool.
- ``retrieve(query, ui_filters)`` — plan and retrieve only; ranked sources, no
  synthesised answer.  Used by the MCP ``search_documents`` tool, where the
  calling agent does its own synthesis and the saved LLM call matters.

The per-query LLM-call budget
-----------------------------
The number of LLM (chat) calls per query is not a fixed ceiling: it follows
``SEARCH_MAX_REFINEMENTS`` — one planner call, one exploratory synthesise, and
one synthesise per refinement pass, i.e. ``2 + SEARCH_MAX_REFINEMENTS``. The
operator sets the refinement count from the UI with no hard cap, so cost and
latency scale linearly with it. The query embedding is not a chat call and is
not counted (spec §6.5).

The budget is enforced two ways, belt and braces:

1. *Structurally* — ``answer`` makes the planner call once, the exploratory
   synthesise once, and then loops the refinement synthesise at most
   ``SEARCH_MAX_REFINEMENTS`` times; the loop counter bounds it.
2. *Defensively* — every LLM stage is invoked through :class:`_LlmBudget`,
   whose ``record`` increments a counter and raises
   :class:`~search.errors.LlmBudgetExceededError` if it ever exceeds the
   per-query limit (``2 + SEARCH_MAX_REFINEMENTS``).  A logic regression that
   tried an extra call would fail loudly here rather than silently overspending
   (CODE_GUIDELINES §1.11).

Allowed deps: search (models, errors, planner, retriever, synthesizer,
    refinement), store (reader, models), common.config.
Forbidden: no FastAPI, no MCP SDK, no sqlite3, no direct LLM/HTTP calls.

# rationale: this file exceeds the §3.1 500-line guideline. Every line is
# load-bearing: the class is a single cohesive orchestrator; its docstrings
# are spec cross-references that cannot be removed without losing traceability
# to §6.3 and §14.3; and the module-level helpers are each cited by tests.
# Splitting _LlmBudget into its own module would add an import edge with no
# cohesion benefit. The Wave 4 simplification audit accepted this length.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from search.cache import build_cache_key, get_search_result_cache, is_cacheable
from search.errors import LlmBudgetExceededError
from search.judge import RelevanceJudge
from search.models import (
    Answered,
    ClarifyNeeded,
    EMPTY_FILTER_CANDIDATES,
    JudgeCandidate,
    NeedsMore,
    QueryPlan,
    RetrievedChunk,
    RetrievalSignal,
    SearchMode,
    SearchResult,
    SearchStats,
    SourceDocument,
)
from search.refinement import (
    adjust_plan,
    broaden_plan,
    merge_chunks,
    trivial_plan,
)
from search.retriever import resolve_filters
from search.relevance import RelevanceThresholds
from search.sources import _snippet, assemble_sources
from search.text import (
    ADJUSTMENT_LOG_PREFIX_CHARS,
    QUERY_LOG_PREFIX_CHARS,
    is_trivial_query,
)
from store import StoreError

if TYPE_CHECKING:
    from common.config import Settings
    from search.cache import _CacheKey
    from search.planner import QueryPlanner
    from search.retriever import Retriever
    from search.synthesizer import Synthesizer
    from store.reader import SearchFilters, StoreReader

log = structlog.get_logger(__name__)

# The per-query LLM-call budget is NOT a fixed ceiling — it follows
# SEARCH_MAX_REFINEMENTS: 1 planner + 1 exploratory synthesise + one synthesise
# per refinement pass = 2 + SEARCH_MAX_REFINEMENTS. The operator sets the
# refinement count from the UI with no hard cap; _LlmBudget still enforces the
# resulting per-request limit as a defensive backstop against a logic
# regression overspending on a billable endpoint. Cost and latency scale
# linearly with the setting.

# Shown as the answer when retrieval yields nothing or Layer 2 rejects the
# signal (spec §6.3, §11).  A no-hits or irrelevant-signal query
# short-circuits before any synthesis call, so there is no model prose.  The
# exact wording is the spec §11 canonical message — changing it here changes
# every no_match path simultaneously.
_NO_MATCHES_ANSWER = (
    "I couldn't find any documents matching that. "
    "Try rephrasing, or broaden your search."
)

# Fixed user-facing answer for the Layer-1 adequacy gate (spec §11).  The
# model's reason is logged for triage but NEVER shown to the user — consistent
# UX requires a single, stable message regardless of which model phrased the
# rejection.
_CLARIFY_ANSWER = (
    "That search is a bit too broad for me to answer well. "
    "Add a detail or two, or use the filters to pick a correspondent or document type."
)


class _LlmBudget:
    """A monotonically-increasing counter enforcing the per-query LLM-call limit.

    The limit is not fixed: it is ``2 + SEARCH_MAX_REFINEMENTS`` (1 planner +
    1 exploratory synthesise + one synthesise per refinement pass), passed in at
    construction. Every LLM chat call in the pipeline is recorded here *before*
    it is made — recording first is what lets ``record`` refuse a call that
    would breach the limit, the defensive backstop against a logic regression
    overspending on a billable endpoint. ``count`` is the number of calls
    *attempted*, not necessarily billed: a stage that degrades to its fallback
    because every model failed (returning no content, with no successful API
    call) is still counted. ``SearchStats.llm_calls`` therefore reports
    attempts; on a fully successful query attempts equal billable calls.
    """

    def __init__(self, max_calls: int) -> None:
        self.count = 0
        self.max_calls = max_calls

    def record(self) -> None:
        """Register one LLM chat call; fail loud if the limit is breached.

        An explicit ``raise`` is used rather than ``assert`` — an ``assert`` is
        stripped under ``python -O``, which would silently disable this cost
        guard on a billable endpoint in exactly the deployments where it
        matters most.

        Raises:
            LlmBudgetExceededError: If recording this call would exceed the
                per-query limit (``2 + SEARCH_MAX_REFINEMENTS``). This is
                unreachable by ``SearchCore``'s own loop logic; it guards
                against a future regression silently overspending
                (CODE_GUIDELINES §1.11).
        """
        self.count += 1
        if self.count > self.max_calls:
            raise LlmBudgetExceededError(
                f"LLM-call limit breached: {self.count} calls made, "
                f"the per-query limit is {self.max_calls} "
                f"(2 + SEARCH_MAX_REFINEMENTS)."
            )


class SearchCore:
    """Orchestrates the bounded agentic search pipeline (spec §6.3).

    The planner, retriever, and synthesiser are injected so the whole pipeline
    is testable offline with a mock LLM client (CODE_GUIDELINES §11.4).  A
    single ``SearchCore`` instance is safe to share across the search server's
    request threads — it holds no per-request state; every call's state lives
    in locals.

    Args:
        settings: Application settings; ``SEARCH_MAX_REFINEMENTS`` and
            ``PAPERLESS_PUBLIC_URL`` are read.
        store_reader: The read-side store interface, for facets and document
            look-ups during source assembly.
        planner: The query-planning stage (LLM call #1).
        retriever: The hybrid retrieval stage (no LLM call).
        synthesizer: The answer-synthesis stage (LLM calls #2 and #3).
        judge: The document-relevance screen (Layer 3, one cheap LLM call).
    """

    def __init__(
        self,
        settings: Settings,
        store_reader: StoreReader,
        planner: QueryPlanner,
        retriever: Retriever,
        synthesizer: Synthesizer,
        judge: RelevanceJudge,
    ) -> None:
        self._settings = settings
        self._store_reader = store_reader
        self._planner = planner
        self._retriever = retriever
        self._synthesizer = synthesizer
        self._judge = judge

    @property
    def settings(self) -> Settings:
        """Return the :class:`Settings` this core was built from.

        Exposed for the per-request hot-reload path in :mod:`search.routes`,
        which reads ``SEARCH_MAX_CONCURRENT`` off the live core to keep the
        ``/api/search`` semaphore in step with the latest configuration
        (web-redesign §5, Wave 4). The attribute is read-only — internal
        consumers continue to use ``self._settings`` directly.
        """
        return self._settings

    def _relevance_thresholds(self) -> RelevanceThresholds:
        """Build the relevance-badge cut-points from the live settings.

        Read per request from ``self._settings`` so a retune of the
        ``SEARCH_RELEVANCE_TIER_*`` knobs hot-loads on the next search (the core
        is rebuilt on a config-version bump) with no restart. The values are
        already validated and ordered by the config layer.
        """
        return RelevanceThresholds(
            strong=self._settings.SEARCH_RELEVANCE_TIER_STRONG,
            good=self._settings.SEARCH_RELEVANCE_TIER_GOOD,
            partial=self._settings.SEARCH_RELEVANCE_TIER_PARTIAL,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def answer(
        self,
        query: str,
        ui_filters: SearchFilters | None = None,
        asker: str | None = None,
    ) -> SearchResult:
        """Run the full pipeline and return a synthesised SearchResult.

        A successful answer is served from / written to the process result
        cache (RAG-05) keyed on the normalised query, the UI filters, a cheap
        index-version signal, and the asker identity. A cache hit makes zero
        LLM calls. The cache is bypassed (fail-open) when the index version
        cannot be read, and a no-match or degraded result is never cached.
        ``SEARCH_CACHE_TTL_SECONDS`` of 0 disables the cache entirely.

        Args:
            query: The raw user search query.
            ui_filters: Explicit user-set filters; when provided they are
                authoritative and bypass free-text filter resolution.
            asker: Optional sanitised display name of the requesting user.
                Threaded to the planner and synthesiser so first-person
                references resolve to the right person, and included in the
                cache key as a cross-user-leak guard.

        Returns:
            A SearchResult with the synthesised answer, ranked source
            documents, the query plan, and execution statistics.
        """
        cache = get_search_result_cache(self._settings.SEARCH_CACHE_TTL_SECONDS)
        cache_key = self._cache_key(query, ui_filters, asker)
        if cache_key is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                log.info(
                    "search.cache_hit", query_prefix=query[:QUERY_LOG_PREFIX_CHARS]
                )
                return cached

        result = self._answer_uncached(query, ui_filters, asker)

        if cache_key is not None and is_cacheable(result):
            cache.put(cache_key, result)
        return result

    def _answer_uncached(
        self,
        query: str,
        ui_filters: SearchFilters | None,
        asker: str | None = None,
    ) -> SearchResult:
        """Run the bounded pipeline once, ignoring the cache.

        The original ``answer`` body — the bounded loop of spec §6.3: plan,
        resolve filters, retrieve, broaden-and-retry once if retrieval is empty,
        synthesise once, and — while the synthesiser asks for more and the
        refinement budget allows — adjust, retrieve again, merge, and
        re-synthesise. At most ``2 + SEARCH_MAX_REFINEMENTS`` LLM calls are made
        (see the module docstring).

        Three fail-fast gates sit at the front of the pipeline (spec §7):

        * **Layer 0** — degenerate-input guard: a query shorter than
          ``SEARCH_MIN_QUERY_CHARS`` characters (after stripping) is rejected
          immediately with ``outcome_kind='clarify'`` and **zero** LLM calls.
        * **Layer 1** — adequacy gate: the planner may return
          :class:`~search.models.ClarifyNeeded` for an obviously-vague query;
          the core short-circuits before retrieval or synthesis.
        * **Layer 2** — relevance gate: when ``SEARCH_GATE_RELEVANCE`` is set,
          retrieved chunks whose best absolute vector similarity is below
          ``SEARCH_RELEVANCE_MIN_SIMILARITY`` *and* that have no keyword hit
          are discarded without synthesis (``outcome_kind='no_match'``).  The
          gate is fail-open: a ``None`` similarity (no vector pass ran) always
          proceeds to synthesis.
        """
        started = time.monotonic()
        judge_call = 1 if self._settings.SEARCH_GATE_JUDGE else 0
        budget = _LlmBudget(
            max_calls=2 + judge_call + self._settings.SEARCH_MAX_REFINEMENTS
        )

        # --- Layer 0: degenerate-input guard (spec §7.0) ---
        if len(query.strip()) < self._settings.SEARCH_MIN_QUERY_CHARS:
            return self._clarify_result(
                "query below SEARCH_MIN_QUERY_CHARS", budget, started
            )

        plan_outcome = self._plan(query, budget, asker)
        if isinstance(plan_outcome, ClarifyNeeded):
            return self._clarify_result(plan_outcome.reason, budget, started)
        plan = plan_outcome

        chunks, signal = self._retrieve_with_broaden(plan, ui_filters)

        if not chunks:
            log.info(
                "search.no_matches",
                query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
            )
            return self._no_match_result(plan, budget, started)

        # --- Layer 2: relevance gate (spec §7.2) ---
        if self._settings.SEARCH_GATE_RELEVANCE and _is_irrelevant(
            signal,
            min_similarity=self._settings.SEARCH_RELEVANCE_MIN_SIMILARITY,
        ):
            log.info(
                "search.synth_skipped_no_relevance",
                query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
                best_vector_similarity=signal.best_vector_similarity,
                has_keyword_hit=signal.has_keyword_hit,
            )
            return self._no_match_result(plan, budget, started)

        # --- Layer 3: document-relevance judge (cheap pre-synthesis screen) ---
        filtered = self._judge_and_filter(query, chunks, budget)
        if filtered is None:
            log.info("search.judge_bailed", query_prefix=query[:QUERY_LOG_PREFIX_CHARS])
            return self._no_match_result(plan, budget, started)
        chunks = filtered

        outcome = self._synthesise(
            query, chunks, mode="exploratory", budget=budget, asker=asker
        )

        # Refine while the synthesiser still wants more context, up to the
        # configured number of passes. Each pass folds the latest hint into the
        # plan, retrieves again, merges into the growing chunk set, and
        # re-synthesises. Intermediate passes stay "exploratory" (may ask for
        # more); the last allowed pass runs in "final" mode (must answer or say
        # not-found), so the loop always terminates with an Answered outcome.
        # The budget (2 + SEARCH_MAX_REFINEMENTS) bounds the calls regardless.
        max_refinements = self._settings.SEARCH_MAX_REFINEMENTS
        refinements = 0
        while isinstance(outcome, NeedsMore) and refinements < max_refinements:
            is_last = refinements + 1 >= max_refinements
            outcome, chunks = self._refine(
                query,
                plan,
                ui_filters,
                outcome,
                chunks,
                budget,
                mode="final" if is_last else "exploratory",
                asker=asker,
            )
            refinements += 1
        refined = refinements > 0

        answer_text = outcome.answer if isinstance(outcome, Answered) else ""
        sources = assemble_sources(
            chunks,
            self._store_reader,
            self._settings.PAPERLESS_PUBLIC_URL,
            self._relevance_thresholds(),
        )
        sources = _cited_sources(sources, outcome)
        return self._build_result(
            answer_text, sources, plan, budget, started, refined=refined
        )

    def _cache_key(
        self,
        query: str,
        ui_filters: SearchFilters | None,
        asker: str | None = None,
    ) -> _CacheKey | None:
        """Build the result-cache key, or None when the index version is unreadable.

        Returning None makes ``answer`` bypass the cache for this request
        (fail-open) — a search must never fail because the cache could not key
        itself (spec §6). The asker is included so two users with different
        identities never share each other's cached answer (cross-user-leak guard).
        """
        index_version = self._index_version()
        if index_version is None:
            return None
        return build_cache_key(
            query=query, filters=ui_filters, index_version=index_version, asker=asker
        )

    def _index_version(self) -> str | None:
        """Return ``document_count:chunk_count`` as the cache index version.

        A change in either count (a document indexed, re-chunked, or pruned)
        moves the version string and invalidates prior cache entries (spec §7).
        A store read failure logs at DEBUG and returns None — the caller then
        bypasses the cache rather than failing the search.
        """
        try:
            stats = self._store_reader.get_stats()
        except StoreError as exc:
            log.debug("search.cache_version_unavailable", error=str(exc))
            return None
        return f"{stats.document_count}:{stats.chunk_count}"

    def retrieve(
        self,
        query: str,
        ui_filters: SearchFilters | None = None,
        asker: str | None = None,
    ) -> SearchResult:
        """Plan and retrieve only — ranked sources, no synthesised answer.

        This is the "sources only" mode behind the MCP ``search_documents``
        tool: the calling agent synthesises its own answer, so the pipeline
        makes only the single planner LLM call and skips synthesis entirely.

        Args:
            query: The raw user search query.
            ui_filters: Explicit user-set filters; authoritative when set.
            asker: Optional sanitised display name of the requesting user,
                threaded to the planner so first-person references resolve
                correctly in the query plan.

        Returns:
            A SearchResult whose ``answer`` is an empty string and whose
            ``sources`` are the ranked retrieved documents.
        """
        started = time.monotonic()
        budget = _LlmBudget(max_calls=2 + self._settings.SEARCH_MAX_REFINEMENTS)

        # Layer 0: degenerate-input guard (spec §7.0) — same check as
        # _answer_uncached so callers always get consistent behaviour.
        if len(query.strip()) < self._settings.SEARCH_MIN_QUERY_CHARS:
            return self._clarify_result(
                "query below SEARCH_MIN_QUERY_CHARS", budget, started
            )

        plan_outcome = self._plan(query, budget, asker)
        if isinstance(plan_outcome, ClarifyNeeded):
            return self._clarify_result(plan_outcome.reason, budget, started)
        plan = plan_outcome

        # Layer 2 does NOT apply here — retrieve() is advisory (spec §7).
        chunks, _signal = self._retrieve_with_broaden(plan, ui_filters)
        sources = assemble_sources(
            chunks,
            self._store_reader,
            self._settings.PAPERLESS_PUBLIC_URL,
            self._relevance_thresholds(),
        )
        return self._build_result("", sources, plan, budget, started, refined=False)

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _plan(
        self, query: str, budget: _LlmBudget, asker: str | None = None
    ) -> QueryPlan | ClarifyNeeded:
        """Run the planner stage, or skip it for a trivial query (RAG-08).

        When ``SEARCH_SKIP_PLANNER_FOR_TRIVIAL`` is set and the query is a
        short, signal-free keyword lookup, the planner LLM call is skipped and
        the fallback-shaped trivial plan is used — retrieval still runs vector +
        FTS on the raw query, so nothing is lost (spec §4.6). The flag defaults
        off, preserving today's always-plan behaviour.

        Returns a ``QueryPlan`` in all normal and fallback cases, or a
        ``ClarifyNeeded`` when the planner's adequacy gate fires (Layer 1).
        """
        if self._settings.SEARCH_SKIP_PLANNER_FOR_TRIVIAL and is_trivial_query(query):
            log.info(
                "search.planner_skipped_trivial",
                query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
            )
            return trivial_plan(query)
        budget.record()
        return self._planner.plan(query, asker=asker)

    def _retrieve_with_broaden(
        self,
        plan: QueryPlan,
        ui_filters: SearchFilters | None,
    ) -> tuple[list[RetrievedChunk], RetrievalSignal]:
        """Retrieve for *plan*; broaden and retry once if nothing is found.

        Resolves the plan's free-text filter candidates against the live
        taxonomy (UI filters bypass resolution), then runs hybrid retrieval.
        An empty result is retried once with the filters dropped (spec §6.3) —
        a mis-resolved or hallucinated filter is the most common cause of an
        otherwise-answerable query returning nothing.  Neither call is an LLM
        call.

        Returns:
            A 2-tuple ``(chunks, signal)`` where *signal* is from whichever
            retrieval pass found chunks (or the broadened pass when the first
            was empty).  The signal is forwarded to Layer 2 in
            ``_answer_uncached``.
        """
        facets = self._store_reader.list_facets()
        filters = resolve_filters(plan.filter_candidates, facets, ui_filters=ui_filters)
        chunks, signal = self._retriever.retrieve(plan, filters)
        if chunks:
            return chunks, signal

        # Empty retrieval — drop the filters and try once more.
        broadened_plan = broaden_plan(plan)
        broadened_filters = resolve_filters(
            broadened_plan.filter_candidates, facets, ui_filters=None
        )
        log.info("search.retrieval_broadened")
        chunks, signal = self._retriever.retrieve(broadened_plan, broadened_filters)
        return chunks, signal

    def _judge_candidates(self, chunks: list[RetrievedChunk]) -> list[JudgeCandidate]:
        """Reduce chunks to one document-level candidate each (best-chunk snippet).

        Keeps each document's highest-rrf_score chunk's text as the snippet —
        the most relevant slice for a relevance call — reusing the same snippet
        trimmer as source assembly (no duplication).
        """
        best_score: dict[int, float] = {}
        snippet: dict[int, str] = {}
        for chunk in chunks:
            current = best_score.get(chunk.document_id)
            if current is None or chunk.rrf_score > current:
                best_score[chunk.document_id] = chunk.rrf_score
                snippet[chunk.document_id] = _snippet(chunk.text)
        return [
            JudgeCandidate(document_id=document_id, snippet=snippet[document_id])
            for document_id in best_score
        ]

    def _judge_and_filter(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        budget: _LlmBudget,
    ) -> list[RetrievedChunk] | None:
        """Judge the retrieved documents; return filtered chunks, or None to bail.

        Returns chunks unchanged when the judge is disabled. Otherwise records
        one budget call, asks the judge which documents are relevant, and:
        bails (None) only on an explicit empty verdict; filters to surviving
        documents otherwise; fails open (all chunks) if filtering keeps nothing.
        """
        if not self._settings.SEARCH_GATE_JUDGE:
            return chunks
        candidates = self._judge_candidates(chunks)
        budget.record()
        verdict = self._judge.judge(query, candidates)
        if not verdict.relevant_document_ids and not verdict.degraded:
            return None
        kept = [c for c in chunks if c.document_id in verdict.relevant_document_ids]
        if not kept:
            return chunks
        if not verdict.degraded:
            dropped = sorted(
                {c.document_id for c in chunks} - verdict.relevant_document_ids
            )
            if dropped:
                log.info(
                    "search.judge_filtered",
                    query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
                    kept=len(verdict.relevant_document_ids),
                    dropped=dropped,
                )
        else:
            log.info(
                "search.judge_degraded", query_prefix=query[:QUERY_LOG_PREFIX_CHARS]
            )
        return kept

    def _synthesise(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        mode: SearchMode,
        budget: _LlmBudget,
        asker: str | None = None,
    ) -> Answered | NeedsMore:
        """Run one synthesiser LLM call, recording it against the budget."""
        budget.record()
        return self._synthesizer.synthesise(query, chunks, mode=mode, asker=asker)

    def _refine(
        self,
        query: str,
        plan: QueryPlan,
        ui_filters: SearchFilters | None,
        needs_more: NeedsMore,
        previous_chunks: list[RetrievedChunk],
        budget: _LlmBudget,
        mode: SearchMode,
        asker: str | None = None,
    ) -> tuple[Answered | NeedsMore, list[RetrievedChunk]]:
        """Run one bounded refinement pass (spec §6.3).

        Folds the synthesiser's adjustment hint into the plan, retrieves again,
        merges the new chunks with the previous round's, and re-synthesises in
        *mode*. The caller runs intermediate passes in ``"exploratory"`` mode
        (which may return another ``NeedsMore`` to continue the loop) and the
        last allowed pass in ``"final"`` mode (which must answer or explicitly
        say "not found"), so the refinement loop always terminates.

        Args:
            query: The raw user query.
            plan: The original query plan.
            ui_filters: The authoritative UI filters, if any.
            needs_more: The previous synthesise's NeedsMore signal.
            previous_chunks: The chunks accumulated so far.
            budget: The LLM-call budget; this synthesise is recorded here.
            mode: ``"exploratory"`` for an intermediate pass, ``"final"`` for
                the last allowed pass.
            asker: Optional sanitised display name of the requesting user,
                forwarded to the synthesiser for first-person resolution.

        Returns:
            A pair of the synthesiser outcome and the merged chunk list used as
            its context (and as the result's source set).
        """
        log.info(
            "search.refined",
            query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
            adjustment=needs_more.adjustment[:ADJUSTMENT_LOG_PREFIX_CHARS],
        )
        adjusted_plan = adjust_plan(plan, needs_more.adjustment)
        new_chunks, _signal = self._retrieve_with_broaden(adjusted_plan, ui_filters)
        merged = merge_chunks(previous_chunks, new_chunks)
        outcome = self._synthesise(query, merged, mode=mode, budget=budget, asker=asker)
        return outcome, merged

    # ------------------------------------------------------------------
    # Result construction
    # ------------------------------------------------------------------

    def _build_result(
        self,
        answer: str,
        sources: tuple[SourceDocument, ...],
        plan: QueryPlan,
        budget: _LlmBudget,
        started: float,
        *,
        refined: bool,
    ) -> SearchResult:
        """Assemble the final SearchResult with execution statistics."""
        stats = SearchStats(
            llm_calls=budget.count,
            latency_ms=_elapsed_ms(started),
            refined=refined,
        )
        return SearchResult(answer=answer, sources=sources, plan=plan, stats=stats)

    def _no_match_result(
        self,
        plan: QueryPlan,
        budget: _LlmBudget,
        started: float,
    ) -> SearchResult:
        """Build the no-hits SearchResult — no sources, no synthesis call.

        Used for both the empty-retrieval case (no chunks found at all) and the
        Layer-2 relevance-gate rejection (chunks found but signal too weak).
        The ``outcome_kind`` is ``"no_match"`` in both cases so callers and the
        SPA can render a consistent "try rephrasing" state.
        """
        stats = SearchStats(
            llm_calls=budget.count,
            latency_ms=_elapsed_ms(started),
            refined=False,
        )
        return SearchResult(
            answer=_NO_MATCHES_ANSWER,
            sources=(),
            plan=plan,
            stats=stats,
            outcome_kind="no_match",
        )

    def _clarify_result(
        self,
        reason: str,
        budget: _LlmBudget,
        started: float,
    ) -> SearchResult:
        """Build the Layer-1 adequacy-gate SearchResult.

        The model's ``reason`` is logged for operator triage; the user-facing
        ``answer`` is the FIXED ``_CLARIFY_ANSWER`` message (spec §11) — the
        model's phrasing is never surfaced directly to preserve consistent UX.

        A minimal QueryPlan whose sole semantic query is the constant clarify
        message string is used as the plan (no retrieval ran, so there is no
        real plan to report; this satisfies the non-null plan contract).

        Args:
            reason: The model's reason for the clarify signal (logged only).
            budget: The LLM budget tracker (reflects the one planner call).
            started: The monotonic timestamp when the request began.

        Returns:
            A SearchResult with outcome_kind='clarify', the fixed answer, empty
            sources, and stats reflecting the single planner call.
        """
        log.info(
            "search.clarify_needed",
            reason=reason,
        )
        # Minimal plan: a single semantic query so callers always get a non-null
        # plan; empty rest because no retrieval ran.
        minimal_plan = QueryPlan(
            semantic_queries=(_CLARIFY_ANSWER,),
            keyword_terms=(),
            filter_candidates=EMPTY_FILTER_CANDIDATES,
            sub_questions=(),
        )
        stats = SearchStats(
            llm_calls=budget.count,
            latency_ms=_elapsed_ms(started),
            refined=False,
        )
        return SearchResult(
            answer=_CLARIFY_ANSWER,
            sources=(),
            plan=minimal_plan,
            stats=stats,
            outcome_kind="clarify",
        )


# ---------------------------------------------------------------------------
# Module-level helpers (no SearchCore state)
# ---------------------------------------------------------------------------


def _elapsed_ms(started: float) -> int:
    """Return whole milliseconds elapsed since the monotonic timestamp *started*."""
    return int((time.monotonic() - started) * 1000)


def _is_irrelevant(signal: RetrievalSignal, *, min_similarity: float) -> bool:
    """Return True when the retrieval signal is too weak to be worth synthesising.

    Conservative and fail-open (spec §7.2):

    * **Reject only when BOTH signals are poor** — the best vector similarity is
      below *min_similarity* AND there is no keyword hit.  An exact-term keyword
      match or a strong semantic match is always allowed through.
    * **Fail-open when similarity is unavailable** — when ``best_vector_similarity``
      is ``None`` (no vector search ran or returned results), the function returns
      ``False`` so synthesis proceeds.  Missing information is not evidence of
      irrelevance.

    Args:
        signal: The :class:`~search.models.RetrievalSignal` from the retriever.
        min_similarity: The absolute vector similarity floor below which retrieval
            is considered irrelevant.  ``0.0`` makes this function always return
            ``False`` (the production interim default until Task 4 calibrates it).

    Returns:
        ``True`` only when both the similarity is known AND is below the floor AND
        there is no keyword hit; ``False`` in every other case (including when
        similarity is unknown).
    """
    if signal.best_vector_similarity is None:
        # No vector data — fail-open, do not reject.
        return False
    return signal.best_vector_similarity < min_similarity and not signal.has_keyword_hit


def _cited_sources(
    sources: tuple[SourceDocument, ...],
    outcome: Answered | NeedsMore,
) -> tuple[SourceDocument, ...]:
    """Narrow assembled sources to the documents the answer actually cited.

    ``SearchResult.sources`` is the *cited* source set (spec §6.4): the frontend
    resolves each ``[n]`` marker by matching ``document_id`` in ``sources``, so a
    returned-but-uncited document is both wrong by contract and noise in the UI
    (SRCH-02). When the synthesiser emitted parseable citations, keep only the
    sources whose document is cited, preserving the existing descending-score
    rank order.

    The fallback is deliberate and safe: if the outcome carries no usable
    citations — a :class:`NeedsMore`, a degraded answer, or a model that simply
    cited nothing — every retrieved source is returned rather than an empty
    list, so a citation-shy answer still shows its supporting documents.

    Args:
        sources: The rank-ordered sources assembled from the retrieved chunks.
        outcome: The synthesiser outcome carrying any document-id citations.

    Returns:
        The cited subset in rank order, or *sources* unchanged when there are
        no citations to filter by.
    """
    if not isinstance(outcome, Answered) or not outcome.citations:
        return sources
    cited_ids = set(outcome.citations)
    cited = tuple(source for source in sources if source.document_id in cited_ids)
    # A citation set that matches no retrieved document (every cited id was
    # hallucinated) leaves nothing to show — fall back to the retrieved set
    # rather than returning an empty, sourceless answer.
    return cited if cited else sources
