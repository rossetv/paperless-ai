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
``SEARCH_MAX_REFINEMENTS`` and the judge gate. The base is one planner call, an
optional judge call, and one exploratory synthesise. Each refinement pass
(Phase 2) re-plans from the synthesiser's gap hint and re-synthesises — and,
unless the re-plan is a no-op, re-judges the merged set — so a pass costs one
re-plan + one synthesise (+ one re-judge when the judge gate is on). The upper
bound is therefore ``2 + j + R * (2 + j)`` where ``j`` is 1 iff the judge gate
is on and ``R`` is ``SEARCH_MAX_REFINEMENTS`` (see :func:`_max_llm_calls`). A
no-op-guard pass skips the re-retrieve and re-judge, so the *actual* count is at
or below this ceiling. The operator sets the refinement count from the UI with
no hard cap, so cost and latency scale with it. The query embedding is not a
chat call and is not counted (spec §6.5).

The budget is enforced two ways, belt and braces:

1. *Structurally* — ``answer`` makes the planner call once, the exploratory
   synthesise once, and then loops the refinement (re-plan + synthesise) at most
   ``SEARCH_MAX_REFINEMENTS`` times; the loop counter bounds it.
2. *Defensively* — every LLM stage is invoked through :class:`_LlmBudget`,
   whose ``record`` increments a counter and raises
   :class:`~search.errors.LlmBudgetExceededError` if it ever exceeds the
   per-query limit (:func:`_max_llm_calls`).  A logic regression that tried an
   extra call would fail loudly here rather than silently overspending
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
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING

import structlog

from search.cache import build_cache_key, get_search_result_cache, is_cacheable
from search.errors import LlmBudgetExceededError
from search.judge import RelevanceJudge
from search.models import (
    Answered,
    ClarifyNeeded,
    Cost,
    CostSummary,
    FilterCandidates,
    JudgeCandidate,
    NeedsMore,
    RetrievalPlan,
    RetrievalSpec,
    RetrievedChunk,
    RetrievalSignal,
    SearchMode,
    SearchResult,
    SearchStats,
    SourceDocument,
)
from search.refinement import (
    broaden_plan,
    merge_chunks,
    trivial_plan,
)
from search.retriever import resolve_specs
from search.relevance import RelevanceThresholds
from search.sources import _snippet, assemble_sources
from search.text import (
    ADJUSTMENT_LOG_PREFIX_CHARS,
    QUERY_LOG_PREFIX_CHARS,
    is_trivial_query,
)
from search.trace import OnEvent, PhaseRecord, PhaseStart, _Telemetry
from store import StoreError

if TYPE_CHECKING:
    from common.config import Settings
    from common.llm import LlmCallUsage
    from search.cache import _CacheKey
    from search.planner import QueryPlanner
    from search.retriever import Retriever
    from search.synthesizer import Synthesizer
    from store.models import FacetSet
    from store.reader import SearchFilters, StoreReader

log = structlog.get_logger(__name__)

# The per-query LLM-call budget is NOT a fixed ceiling — it follows
# SEARCH_MAX_REFINEMENTS and the judge gate (see _max_llm_calls): 1 planner +
# optional judge + 1 exploratory synthesise, plus one (re-plan + synthesise [+
# re-judge]) per refinement pass. The operator sets the refinement count from
# the UI with no hard cap; _LlmBudget still enforces the resulting per-request
# limit as a defensive backstop against a logic regression overspending on a
# billable endpoint. Cost and latency scale with the setting.

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

    The limit is not fixed: it follows ``SEARCH_MAX_REFINEMENTS`` and the judge
    gate (see :func:`_max_llm_calls`), passed in at construction as *max_calls*.
    Every LLM chat call in the pipeline is recorded here *before*
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
                per-query limit (:func:`_max_llm_calls`). This is unreachable by
                ``SearchCore``'s own loop logic; it guards against a future
                regression silently overspending (CODE_GUIDELINES §1.11).
        """
        self.count += 1
        if self.count > self.max_calls:
            raise LlmBudgetExceededError(
                f"LLM-call limit breached: {self.count} calls made, "
                f"the per-query limit is {self.max_calls}."
            )


@dataclass(frozen=True, slots=True)
class _RetrievalPhaseResult:
    """The output of :meth:`SearchCore._retrieve_phase`.

    Carries the retrieved chunks and signal alongside the resolved pass-1 specs
    and the facets used to resolve them, so the refinement pass can re-plan
    against the same taxonomy and run its no-op guard (does the re-plan resolve
    to the same specs?) without a second ``list_facets`` round-trip. A small
    frozen carrier beats a 4-tuple the caller would have to unpack positionally
    (CODE_GUIDELINES §5.8).
    """

    chunks: list[RetrievedChunk]
    signal: RetrievalSignal
    specs: tuple[RetrievalSpec, ...]
    facets: FacetSet


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
        on_event: OnEvent | None = None,
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
            on_event: Optional callback fed a :class:`~search.trace.PhaseStart`
                then a :class:`~search.models.PhaseRecord` for each executed
                pipeline phase (the live-streaming route). ``None`` (the
                default) makes the pipeline byte-identical for MCP/REST/tests —
                the trace/cost are still assembled onto ``SearchStats``. On a
                cache hit a single ``cache`` phase is emitted before the cached
                result is returned, so a streamed search always produces at
                least one terminal phase.

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
                if on_event is not None:
                    self._emit_cache_phase(on_event, cached)
                return cached

        result = self._answer_uncached(query, ui_filters, asker, on_event=on_event)

        if cache_key is not None and is_cacheable(result):
            cache.put(cache_key, result)
        return result

    @staticmethod
    def _emit_cache_phase(on_event: OnEvent, cached: SearchResult) -> None:
        """Emit the synthetic ``cache`` phase for a cache hit.

        A cache hit does no pipeline work, but a streamed search still needs a
        terminal phase. This emits a ``PhaseStart`` then a zero-cost
        ``PhaseRecord`` whose detail surfaces the *original* (now-saved) cost so
        the SPA can show "served from cache (saved $X)".
        """
        on_event(PhaseStart(phase="cache", label="Served from cache"))
        on_event(
            PhaseRecord(
                phase="cache",
                label="Served from cache",
                detail={
                    "from_cache": True,
                    "original_cost": _cost_dict(cached.stats.cost),
                },
                tokens=None,
                cost=Cost(0.0, cached.stats.cost.local),
                ms=0,
            )
        )

    def _answer_uncached(
        self,
        query: str,
        ui_filters: SearchFilters | None,
        asker: str | None = None,
        on_event: OnEvent | None = None,
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
        tele = _Telemetry(on_event, self._settings.LLM_PROVIDER)
        budget = _LlmBudget(max_calls=_max_llm_calls(self._settings))

        # --- Layer 0: degenerate-input guard (spec §7.0) ---
        # Emitted before any phase, so the trace is empty (no work was done).
        if len(query.strip()) < self._settings.SEARCH_MIN_QUERY_CHARS:
            return self._clarify_result(
                "query below SEARCH_MIN_QUERY_CHARS", budget, started, tele
            )

        # --- Plan (Layer 1 lives inside the planner) ---
        plan_outcome = self._plan_phase(query, budget, asker, tele)
        if isinstance(plan_outcome, ClarifyNeeded):
            return self._clarify_result(plan_outcome.reason, budget, started, tele)
        plan = plan_outcome

        # --- Retrieve (broaden-and-retry once) ---
        retrieved = self._retrieve_phase(plan, ui_filters, tele)
        chunks, signal = retrieved.chunks, retrieved.signal
        current_specs = retrieved.specs
        if not chunks:
            log.info(
                "search.no_matches",
                query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
            )
            return self._no_match_result(plan, budget, started, tele)

        # --- Layer 2: relevance gate (spec §7.2) ---
        if self._settings.SEARCH_GATE_RELEVANCE and self._gate_rejects(
            signal, chunks, tele
        ):
            log.info(
                "search.synth_skipped_no_relevance",
                query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
                best_vector_similarity=signal.best_vector_similarity,
                has_keyword_hit=signal.has_keyword_hit,
            )
            return self._no_match_result(plan, budget, started, tele)

        # --- Layer 3: document-relevance judge (cheap pre-synthesis screen) ---
        filtered = self._judge_and_filter(query, chunks, budget, tele)
        if filtered is None:
            log.info("search.judge_bailed", query_prefix=query[:QUERY_LOG_PREFIX_CHARS])
            return self._no_match_result(plan, budget, started, tele)
        chunks = filtered

        outcome = self._synthesise(
            query, chunks, mode="exploratory", budget=budget, asker=asker, tele=tele
        )

        # Refine while the synthesiser still wants more context, up to the
        # configured number of passes. Each pass re-plans from the synthesiser's
        # gap hint (Phase 2), resolves the new specs, and — unless they are a
        # no-op repeat of what was already tried — retrieves again, merges into
        # the growing chunk set, re-judges, and re-synthesises. Intermediate
        # passes stay "exploratory" (may ask for more); the last allowed pass
        # runs in "final" mode (must answer or say not-found), so the loop always
        # terminates with an Answered outcome. The budget bounds the calls.
        max_refinements = self._settings.SEARCH_MAX_REFINEMENTS
        refinements = 0
        while isinstance(outcome, NeedsMore) and refinements < max_refinements:
            is_last = refinements + 1 >= max_refinements
            outcome, chunks, current_specs = self._refine(
                query,
                outcome,
                chunks,
                current_specs,
                retrieved.facets,
                ui_filters,
                budget,
                mode="final" if is_last else "exploratory",
                asker=asker,
                tele=tele,
                pass_number=refinements + 1,
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
            answer_text, sources, plan, budget, started, tele, refined=refined
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
        on_event: OnEvent | None = None,
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
            on_event: Optional per-phase event callback (plan + retrieve only,
                no synthesis here). ``None`` keeps behaviour unchanged; the
                trace/cost are assembled onto the result either way.

        Returns:
            A SearchResult whose ``answer`` is an empty string and whose
            ``sources`` are the ranked retrieved documents.
        """
        started = time.monotonic()
        tele = _Telemetry(on_event, self._settings.LLM_PROVIDER)
        budget = _LlmBudget(max_calls=_max_llm_calls(self._settings))

        # Layer 0: degenerate-input guard (spec §7.0) — same check as
        # _answer_uncached so callers always get consistent behaviour.
        if len(query.strip()) < self._settings.SEARCH_MIN_QUERY_CHARS:
            return self._clarify_result(
                "query below SEARCH_MIN_QUERY_CHARS", budget, started, tele
            )

        plan_outcome = self._plan_phase(query, budget, asker, tele)
        if isinstance(plan_outcome, ClarifyNeeded):
            return self._clarify_result(plan_outcome.reason, budget, started, tele)
        plan = plan_outcome

        # Layer 2 does NOT apply here — retrieve() is advisory (spec §7).
        retrieved = self._retrieve_phase(plan, ui_filters, tele)
        sources = assemble_sources(
            retrieved.chunks,
            self._store_reader,
            self._settings.PAPERLESS_PUBLIC_URL,
            self._relevance_thresholds(),
        )
        return self._build_result(
            "", sources, plan, budget, started, tele, refined=False
        )

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _plan_phase(
        self,
        query: str,
        budget: _LlmBudget,
        asker: str | None,
        tele: _Telemetry,
    ) -> RetrievalPlan | ClarifyNeeded:
        """Run the plan stage, emitting the ``plan`` phase with its detail.

        Wraps :meth:`_plan` with the telemetry start/done pair, capturing the
        planner call's token usage in a fresh sink (empty for the trivial-skip
        path, which makes no LLM call). The detail carries the rewritten query,
        the planner's per-spec filter guesses, the human-readable spec list, and
        whether the trivial skip fired — the SPA renders these as the "Planning"
        step.
        """
        tele.start("plan", "Planning the query")
        started = time.monotonic()
        sink: list[LlmCallUsage] = []
        skipped_trivial = (
            self._settings.SEARCH_SKIP_PLANNER_FOR_TRIVIAL and is_trivial_query(query)
        )
        outcome = self._plan(query, budget, asker, usage_sink=sink)
        plan = outcome if isinstance(outcome, RetrievalPlan) else None
        tele.done(
            "plan",
            "Planning the query",
            {
                "rewritten_query": _rewritten_query(plan, query),
                "filters": _filter_detail(plan),
                "specs": _spec_detail(plan),
                "skipped_trivial": skipped_trivial,
            },
            usage_sink=sink,
            started=started,
        )
        return outcome

    def _plan(
        self,
        query: str,
        budget: _LlmBudget,
        asker: str | None = None,
        usage_sink: list[LlmCallUsage] | None = None,
    ) -> RetrievalPlan | ClarifyNeeded:
        """Run the planner stage, or skip it for a trivial query (RAG-08).

        When ``SEARCH_SKIP_PLANNER_FOR_TRIVIAL`` is set and the query is a
        short, signal-free keyword lookup, the planner LLM call is skipped and
        the fallback-shaped trivial plan is used — retrieval still runs vector +
        FTS on the raw query, so nothing is lost (spec §4.6). The flag defaults
        off, preserving today's always-plan behaviour.

        ``usage_sink``, when given, receives the planner call's token usage; the
        trivial-skip path makes no LLM call and leaves it empty.

        Returns a ``RetrievalPlan`` in all normal and fallback cases, or a
        ``ClarifyNeeded`` when the planner's adequacy gate fires (Layer 1).
        """
        if self._settings.SEARCH_SKIP_PLANNER_FOR_TRIVIAL and is_trivial_query(query):
            log.info(
                "search.planner_skipped_trivial",
                query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
            )
            return trivial_plan(query)
        budget.record()
        return self._planner.plan(query, asker=asker, usage_sink=usage_sink)

    def _retrieve_phase(
        self,
        plan: RetrievalPlan,
        ui_filters: SearchFilters | None,
        tele: _Telemetry,
    ) -> _RetrievalPhaseResult:
        """Resolve the plan's specs then retrieve, emitting both phases.

        Fetches the live taxonomy once, emits the non-LLM ``resolve`` phase (the
        per-spec resolved ids/dates and the guesses that did not resolve), then
        the ``retrieve`` phase with the chunk/document counts and whether the
        broadened (filter-dropped) second pass ran.  Neither phase is an LLM
        call, so neither carries tokens.  The facets are fetched here and reused
        across both the first and the broadened retrieval pass.

        The resolved pass-1 specs and the fetched facets ride on the returned
        :class:`_RetrievalPhaseResult` so the refinement pass can re-plan against
        the same taxonomy and run the no-op guard without a second
        ``list_facets`` round-trip.
        """
        facets = self._store_reader.list_facets()
        today = date.today()
        specs = resolve_specs(plan, facets, ui_filters=ui_filters, today=today)
        self._emit_resolve_phase(plan, specs, tele)

        tele.start("retrieve", "Retrieving documents")
        started = time.monotonic()
        chunks, signal, broadened = self._retrieve_with_broaden(
            plan, specs, ui_filters, facets, today
        )
        tele.done(
            "retrieve",
            "Retrieving documents",
            {
                "chunk_count": len(chunks),
                "doc_count": len({c.document_id for c in chunks}),
                "broadened": broadened,
            },
            usage_sink=[],
            started=started,
        )
        return _RetrievalPhaseResult(
            chunks=chunks, signal=signal, specs=specs, facets=facets
        )

    @staticmethod
    def _emit_resolve_phase(
        plan: RetrievalPlan,
        specs: tuple[RetrievalSpec, ...],
        tele: _Telemetry,
    ) -> None:
        """Emit the non-LLM ``resolve`` phase: resolved ids/dates + dropped guesses.

        ``resolved`` lists each spec's taxonomy ids and ISO date bounds after
        resolution; ``dropped`` lists the name guesses that were present in the
        plan but did not resolve to a real id (correspondent / document type /
        each tag).  Both are JSON-serialisable primitives the SPA renders as the
        "Resolving filters" step.
        """
        tele.start("resolve", "Resolving filters")
        started = time.monotonic()
        tele.done(
            "resolve",
            "Resolving filters",
            {
                "resolved": [
                    {
                        "spec_index": index,
                        "correspondent_id": spec.filters.correspondent_id,
                        "document_type_id": spec.filters.document_type_id,
                        "tag_ids": list(spec.filters.tag_ids),
                        "date_from": spec.filters.date_from,
                        "date_to": spec.filters.date_to,
                    }
                    for index, spec in enumerate(specs)
                ],
                "dropped": _dropped_guesses(plan, specs),
            },
            usage_sink=[],
            started=started,
        )

    def _gate_rejects(
        self,
        signal: RetrievalSignal,
        chunks: list[RetrievedChunk],
        tele: _Telemetry,
    ) -> bool:
        """Run the Layer-2 relevance gate, emitting the ``gate`` phase.

        The gate is a BINARY aggregate decision over the retrieval signal — it
        does not drop individual documents — so the detail reports the signal
        and a single ``rejected`` boolean, never a per-document drop list (those
        happen at the judge). Returns True when the signal is too weak to
        synthesise from.
        """
        tele.start("gate", "Relevance gate")
        started = time.monotonic()
        min_similarity = self._settings.SEARCH_RELEVANCE_MIN_SIMILARITY
        rejected = _is_irrelevant(signal, min_similarity=min_similarity)
        tele.done(
            "gate",
            "Relevance gate",
            {
                "evaluated": len({c.document_id for c in chunks}),
                "min_similarity": min_similarity,
                "best_similarity": signal.best_vector_similarity,
                "has_keyword_hit": signal.has_keyword_hit,
                "rejected": rejected,
            },
            usage_sink=[],
            started=started,
        )
        return rejected

    def _retrieve_with_broaden(
        self,
        plan: RetrievalPlan,
        specs: tuple[RetrievalSpec, ...],
        ui_filters: SearchFilters | None,
        facets: FacetSet,
        today: date,
    ) -> tuple[list[RetrievedChunk], RetrievalSignal, bool]:
        """Retrieve for the resolved *specs*; broaden and retry once if empty.

        Runs hybrid retrieval over the already-resolved *specs*.  An empty
        result is retried once with every spec's filters dropped (spec §6.3) — a
        mis-resolved or hallucinated filter is the most common cause of an
        otherwise-answerable query returning nothing.  The broadened pass
        re-resolves :func:`~search.refinement.broaden_plan`'s output against the
        same *facets* (no second ``list_facets`` round-trip) with no UI filters,
        so a UI-set filter the user explicitly chose does not survive the
        broaden.  Neither call is an LLM call.

        Returns:
            A 3-tuple ``(chunks, signal, broadened)`` where *signal* is from
            whichever retrieval pass found chunks (or the broadened pass when
            the first was empty) and *broadened* is True iff the second
            (filter-dropped) pass ran. The signal is forwarded to Layer 2 and
            *broadened* feeds the retrieve-phase detail.
        """
        chunks, signal = self._retriever.retrieve(specs)
        if chunks:
            return chunks, signal, False

        # Empty retrieval — drop every spec's filters and try once more.
        broadened_specs = resolve_specs(
            broaden_plan(plan), facets, ui_filters=None, today=today
        )
        log.info("search.retrieval_broadened")
        chunks, signal = self._retriever.retrieve(broadened_specs)
        return chunks, signal, True

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
        tele: _Telemetry,
    ) -> list[RetrievedChunk] | None:
        """Judge the retrieved documents; return filtered chunks, or None to bail.

        Returns chunks unchanged when the judge is disabled (no ``judge`` phase
        is emitted then). Otherwise records one budget call, asks the judge
        which documents are relevant, emits the ``judge`` phase carrying the
        per-document verdicts (capturing the call's token usage), and: bails
        (None) only on an explicit empty verdict; filters to surviving documents
        otherwise; fails open (all chunks) if filtering keeps nothing.
        """
        if not self._settings.SEARCH_GATE_JUDGE:
            return chunks
        candidates = self._judge_candidates(chunks)
        tele.start("judge", "Judging relevance")
        started = time.monotonic()
        sink: list[LlmCallUsage] = []
        budget.record()
        verdict = self._judge.judge(query, candidates, usage_sink=sink)
        bailed = not verdict.relevant_document_ids and not verdict.degraded
        tele.done(
            "judge",
            "Judging relevance",
            {
                "degraded": verdict.degraded,
                "bailed": bailed,
                "verdicts": [
                    {
                        "doc_id": dv.document_id,
                        # Titles are not carried on RetrievedChunk; resolving
                        # them here would cost an extra store read. The client
                        # falls back to the source list for the title, so None
                        # is the honest cheap value (plan §Task 10).
                        "title": None,
                        "keep": dv.keep,
                        "reason": dv.reason,
                    }
                    for dv in verdict.verdicts
                ],
            },
            usage_sink=sink,
            started=started,
        )
        if bailed:
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
        tele: _Telemetry,
    ) -> Answered | NeedsMore:
        """Run one synthesiser LLM call, emit the ``synthesise`` phase, budget it.

        One ``synthesise`` phase is emitted per call (the exploratory pass and
        each refinement pass), carrying the mode and whether the model asked for
        more context, plus the call's token usage.
        """
        tele.start("synthesise", "Synthesising the answer")
        started = time.monotonic()
        sink: list[LlmCallUsage] = []
        budget.record()
        outcome = self._synthesizer.synthesise(
            query, chunks, mode=mode, asker=asker, usage_sink=sink
        )
        tele.done(
            "synthesise",
            "Synthesising the answer",
            {"mode": mode, "needs_more": isinstance(outcome, NeedsMore)},
            usage_sink=sink,
            started=started,
        )
        return outcome

    def _refine(
        self,
        query: str,
        needs_more: NeedsMore,
        previous_chunks: list[RetrievedChunk],
        prior_specs: tuple[RetrievalSpec, ...],
        facets: FacetSet,
        ui_filters: SearchFilters | None,
        budget: _LlmBudget,
        *,
        mode: SearchMode,
        asker: str | None = None,
        tele: _Telemetry,
        pass_number: int,
    ) -> tuple[Answered | NeedsMore, list[RetrievedChunk], tuple[RetrievalSpec, ...]]:
        """Run one bounded refinement pass driven by the synth's gap hint (Phase 2).

        Rather than blindly broadening, the pass RE-PLANS: it asks the planner
        for DIFFERENT specs that target ``needs_more.adjustment``, given the
        specs already tried (*prior_specs*) and the documents already found. The
        re-plan output is resolved against the cached *facets* and compared to
        the prior specs:

        - **No-op guard.** When the re-plan resolves to the *same* specs already
          tried (a re-plan that changed nothing), the pass does NOT retrieve or
          re-judge again — those would be a redundant, billable round-trip for an
          identical result. It runs exactly one final :meth:`_synthesise` on the
          existing evidence and returns. (The exploratory pass already returned
          NeedsMore, so a final answer is still owed.)
        - **Otherwise.** It retrieves for the new specs, merges with the previous
          round's chunks, re-judges the merged set, and re-synthesises in *mode*.

        A re-plan that returns :class:`ClarifyNeeded` is ignored — refinement is
        a best-effort improvement, never a place to start asking the user to
        clarify — and the pass falls through to a single final synthesise on the
        existing chunks, exactly like the no-op path.

        The re-plan LLM call's token usage is captured and attributed to its own
        ``replan`` phase (mirroring the ``plan`` phase); the ``refine`` marker
        phase that follows carries no tokens of its own — the inner
        :meth:`_synthesise` emits the synthesise phase with that pass's cost.

        Args:
            query: The raw user query.
            needs_more: The previous synthesise's NeedsMore signal (the gap hint).
            previous_chunks: The chunks accumulated so far.
            prior_specs: The resolved specs already tried (pass 1, or the prior
                refinement pass), fed to the re-plan and the no-op comparison.
            facets: The taxonomy, cached from the first retrieve, reused to
                resolve the re-plan with no extra ``list_facets`` round-trip.
            ui_filters: The authoritative UI filters, if any.
            budget: The LLM-call budget; the re-plan and synthesise are recorded.
            mode: ``"exploratory"`` for an intermediate pass, ``"final"`` for
                the last allowed pass.
            asker: Optional sanitised display name of the requesting user.
            tele: The per-request telemetry accumulator.
            pass_number: The 1-based refinement pass index, for the detail.

        Returns:
            A triple of the synthesiser outcome, the chunk list used as its
            context (and the result's source set), and the resolved specs now in
            effect (the new specs, or *prior_specs* on a no-op / clarify) — so
            the next pass re-plans against what was actually tried.
        """
        log.info(
            "search.refined",
            query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
            adjustment=needs_more.adjustment[:ADJUSTMENT_LOG_PREFIX_CHARS],
        )
        prior_findings = self._finding_titles(previous_chunks)
        replan_outcome = self._replan_phase(
            query,
            needs_more.adjustment,
            prior_specs,
            prior_findings,
            budget,
            asker,
            tele,
        )

        # A clarify on a re-plan is ignored: finalise on the existing evidence.
        if isinstance(replan_outcome, ClarifyNeeded):
            self._emit_refine_marker(
                needs_more.adjustment, [], len(previous_chunks), noop=True, tele=tele
            )
            outcome = self._synthesise(
                query, previous_chunks, mode=mode, budget=budget, asker=asker, tele=tele
            )
            return outcome, previous_chunks, prior_specs

        new_specs = resolve_specs(
            replan_outcome, facets, ui_filters=ui_filters, today=date.today()
        )

        # No-op guard: a re-plan that resolves to the same specs already tried
        # must not pay for a redundant retrieve + judge — just finalise.
        if _specs_equal(new_specs, prior_specs):
            self._emit_refine_marker(
                needs_more.adjustment, [], len(previous_chunks), noop=True, tele=tele
            )
            outcome = self._synthesise(
                query, previous_chunks, mode=mode, budget=budget, asker=asker, tele=tele
            )
            return outcome, previous_chunks, prior_specs

        new_chunks, _signal = self._retriever.retrieve(new_specs)
        merged = merge_chunks(previous_chunks, new_chunks)
        self._emit_refine_marker(
            needs_more.adjustment,
            _spec_detail_for_resolved(new_specs),
            len(previous_chunks),
            noop=False,
            tele=tele,
        )
        # Re-judge the merged set; a bail here falls back to the merged chunks —
        # mid-refine we already had relevant evidence, so we never downgrade to
        # no_match, we just answer from what we have.
        judged = self._judge_and_filter(query, merged, budget, tele)
        kept = judged if judged is not None else merged
        outcome = self._synthesise(
            query, kept, mode=mode, budget=budget, asker=asker, tele=tele
        )
        return outcome, kept, new_specs

    def _finding_titles(self, chunks: list[RetrievedChunk]) -> tuple[str, ...]:
        """Return the titles of the documents in *chunks*, for the re-plan turn.

        Resolves each distinct document id to its indexed title via
        ``get_documents`` (the same look-up source assembly uses). A document
        with no title, or one no longer in the index, is dropped — the re-plan
        only needs the titles it can name. Order follows first appearance in
        *chunks* (descending fused score), so the strongest findings lead.
        """
        seen: list[int] = []
        for chunk in chunks:
            if chunk.document_id not in seen:
                seen.append(chunk.document_id)
        if not seen:
            return ()
        by_id = {doc.id: doc for doc in self._store_reader.get_documents(seen)}
        titles: list[str] = []
        for document_id in seen:
            doc = by_id.get(document_id)
            if doc is not None and doc.title:
                titles.append(doc.title)
        return tuple(titles)

    def _replan_phase(
        self,
        query: str,
        hint: str,
        prior_specs: tuple[RetrievalSpec, ...],
        prior_findings: tuple[str, ...],
        budget: _LlmBudget,
        asker: str | None,
        tele: _Telemetry,
    ) -> RetrievalPlan | ClarifyNeeded:
        """Run the re-plan stage, emitting the ``replan`` phase with its usage.

        Mirrors :meth:`_plan_phase`: records one budget call, captures the
        re-plan call's token usage in a fresh sink, and emits a ``replan`` phase
        carrying the gap hint and the human-readable new specs (or the clarify
        reason). The token cost is attributed here, never folded into the
        ``refine`` marker, so per-phase accounting stays honest.
        """
        tele.start("replan", "Re-planning")
        started = time.monotonic()
        sink: list[LlmCallUsage] = []
        budget.record()
        outcome = self._planner.replan(
            query,
            hint=hint,
            prior_specs=prior_specs,
            prior_findings=prior_findings,
            asker=asker,
            usage_sink=sink,
        )
        plan = outcome if isinstance(outcome, RetrievalPlan) else None
        tele.done(
            "replan",
            "Re-planning",
            {
                "hint": hint,
                "specs": _spec_detail(plan),
                "clarify": isinstance(outcome, ClarifyNeeded),
            },
            usage_sink=sink,
            started=started,
        )
        return outcome

    @staticmethod
    def _emit_refine_marker(
        adjustment: str,
        new_specs_detail: list[dict[str, object]],
        carried_over: int,
        *,
        noop: bool,
        tele: _Telemetry,
    ) -> None:
        """Emit the non-LLM ``refine`` marker phase describing the pass's action.

        Carries the gap that prompted the pass, a human-readable ``action``, the
        new specs (empty on a no-op), how many chunks were carried over from the
        previous round, and the ``noop`` flag. No tokens — the re-plan and
        synthesise carry their own.
        """
        action = (
            "no new searches → finalising on current evidence"
            if noop
            else f"re-planned: {len(new_specs_detail)} new searches"
        )
        tele.start("refine", "Refining")
        started = time.monotonic()
        tele.done(
            "refine",
            "Refining",
            {
                "gap": adjustment,
                "action": action,
                "new_specs": new_specs_detail,
                "carried_over": carried_over,
                "noop": noop,
            },
            usage_sink=[],
            started=started,
        )

    # ------------------------------------------------------------------
    # Result construction
    # ------------------------------------------------------------------

    def _build_result(
        self,
        answer: str,
        sources: tuple[SourceDocument, ...],
        plan: RetrievalPlan,
        budget: _LlmBudget,
        started: float,
        tele: _Telemetry,
        *,
        refined: bool,
    ) -> SearchResult:
        """Assemble the final SearchResult with execution statistics.

        The assembled per-phase trace and the whole-query cost summary from
        *tele* ride on the :class:`SearchStats` so they are cacheable and reach
        every consumer.
        """
        stats = SearchStats(
            llm_calls=budget.count,
            latency_ms=_elapsed_ms(started),
            refined=refined,
            trace=tele.trace(),
            cost=tele.cost_summary(),
        )
        return SearchResult(answer=answer, sources=sources, plan=plan, stats=stats)

    def _no_match_result(
        self,
        plan: RetrievalPlan,
        budget: _LlmBudget,
        started: float,
        tele: _Telemetry,
    ) -> SearchResult:
        """Build the no-hits SearchResult — no sources, no synthesis call.

        Used for both the empty-retrieval case (no chunks found at all) and the
        Layer-2 relevance-gate rejection (chunks found but signal too weak).
        The ``outcome_kind`` is ``"no_match"`` in both cases so callers and the
        SPA can render a consistent "try rephrasing" state. The trace/cost
        accumulated up to the short-circuit ride on the stats.
        """
        stats = SearchStats(
            llm_calls=budget.count,
            latency_ms=_elapsed_ms(started),
            refined=False,
            trace=tele.trace(),
            cost=tele.cost_summary(),
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
        tele: _Telemetry,
    ) -> SearchResult:
        """Build the Layer-1 adequacy-gate SearchResult.

        The model's ``reason`` is logged for operator triage; the user-facing
        ``answer`` is the FIXED ``_CLARIFY_ANSWER`` message (spec §11) — the
        model's phrasing is never surfaced directly to preserve consistent UX.

        A minimal RetrievalPlan carrying its ``clarify`` signal and no specs is
        used as the plan (no retrieval ran, so there is no real plan to report;
        this satisfies the non-null plan contract).

        Args:
            reason: The model's reason for the clarify signal (logged only).
            budget: The LLM budget tracker (reflects the one planner call).
            started: The monotonic timestamp when the request began.
            tele: The per-request telemetry accumulator. For the Layer-0
                degenerate-input clarify this has no phases (empty trace, zero
                cost); for the Layer-1 planner clarify it carries the plan phase.

        Returns:
            A SearchResult with outcome_kind='clarify', the fixed answer, empty
            sources, and stats reflecting the single planner call.
        """
        log.info(
            "search.clarify_needed",
            reason=reason,
        )
        # Minimal plan: no specs (no retrieval ran) carrying the clarify signal,
        # so callers always get a non-null plan.
        minimal_plan = RetrievalPlan(specs=(), clarify=ClarifyNeeded(reason=reason))
        stats = SearchStats(
            llm_calls=budget.count,
            latency_ms=_elapsed_ms(started),
            refined=False,
            trace=tele.trace(),
            cost=tele.cost_summary(),
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


def _max_llm_calls(settings: Settings) -> int:
    """Return the per-query LLM-call upper bound for the ``_LlmBudget`` backstop.

    The bound is **not** fixed — it follows ``SEARCH_MAX_REFINEMENTS`` and
    whether the judge gate is on:

    - **1** planner call.
    - **1** exploratory synthesise.
    - **+1** judge call when ``SEARCH_GATE_JUDGE`` is on (the pass-1 screen).
    - per refinement pass (Phase 2): **1** re-plan + **1** synthesise, plus
      **1** re-judge when the judge gate is on. A no-op-guard pass skips the
      re-retrieve and re-judge, so it costs strictly fewer than this bound — the
      backstop is an *upper* bound, never an exact count.

    So the limit is ``2 + j + R * (2 + j)`` where ``j`` is 1 iff the judge gate
    is on and ``R`` is ``SEARCH_MAX_REFINEMENTS``. This is the defensive ceiling
    ``_LlmBudget`` enforces; the loop's own structure keeps the actual count at
    or below it.
    """
    judge_call = 1 if settings.SEARCH_GATE_JUDGE else 0
    refinements = settings.SEARCH_MAX_REFINEMENTS
    return 2 + judge_call + refinements * (2 + judge_call)


def _cost_dict(cs: CostSummary) -> dict[str, object]:
    """Flatten a :class:`CostSummary` to a JSON-friendly dict for a phase detail.

    Used for the cache-hit phase's ``original_cost`` so the SPA can show what
    the cached answer originally cost (and therefore what the cache hit saved).
    """
    return {
        "tokens": {
            "prompt": cs.tokens.prompt,
            "completion": cs.tokens.completion,
            "reasoning": cs.tokens.reasoning,
            "total": cs.tokens.total,
        },
        "usd": cs.usd,
        "local": cs.local,
        "llm_calls": cs.llm_calls,
    }


def _rewritten_query(plan: RetrievalPlan | None, query: str) -> str:
    """Return the first spec's semantic text as the plan's "rewritten query".

    Falls back to the raw *query* when there is no plan (a clarify outcome) or
    no spec carries semantic text (e.g. a keyword-only plan) — the SPA always
    has a non-empty "Planning" label to show.
    """
    if plan is None:
        return query
    for spec in plan.specs:
        if spec.semantic:
            return spec.semantic
    return query


def _filter_detail(plan: RetrievalPlan | None) -> dict[str, object]:
    """Build the plan phase's ``filters`` detail from the plan's filter guesses.

    Reports the planner's non-empty free-text filter-guess *names* (the
    human-readable guesses available at plan time), not the resolved taxonomy
    ids — resolution to ids happens in the ``resolve`` phase. The guesses across
    all specs are merged: the first non-None correspondent / document-type wins,
    tags and date bounds are unioned. Empty / None guesses are omitted, so a
    plan with no filters yields ``{}``.
    """
    if plan is None:
        return {}
    detail: dict[str, object] = {}
    tags: list[str] = []
    for spec in plan.specs:
        fg = spec.filter_guess
        if "correspondent" not in detail and fg.correspondent is not None:
            detail["correspondent"] = fg.correspondent
        if "document_type" not in detail and fg.document_type is not None:
            detail["document_type"] = fg.document_type
        for tag in fg.tags:
            if tag not in tags:
                tags.append(tag)
        if "date_from" not in detail and fg.date_from is not None:
            detail["date_from"] = fg.date_from
        if "date_to" not in detail and fg.date_to is not None:
            detail["date_to"] = fg.date_to
    if tags:
        detail["tags"] = tags
    return detail


def _spec_detail(plan: RetrievalPlan | None) -> list[dict[str, object]]:
    """Build the plan phase's ``specs`` detail — one entry per planned spec.

    Each entry carries the spec's mode, a human-readable query (the semantic
    text, or the joined keywords for a keyword spec), the spec's pre-resolution
    filter guesses, and its rationale — all JSON-serialisable primitives the SPA
    renders. An absent plan (a clarify outcome) yields ``[]``.
    """
    if plan is None:
        return []
    return [
        {
            "mode": spec.mode,
            "query": spec.semantic or " ".join(spec.keywords),
            "filters": _guess_dict(spec.filter_guess),
            "rationale": spec.rationale,
        }
        for spec in plan.specs
    ]


def _spec_detail_for_resolved(
    specs: tuple[RetrievalSpec, ...],
) -> list[dict[str, object]]:
    """Render resolved specs for the ``refine`` phase's ``new_specs`` detail.

    Each entry carries the spec's mode, a human-readable query (semantic text or
    joined keywords), the resolved taxonomy ids / ISO date bounds, and the
    rationale — all JSON-serialisable primitives the SPA renders as "the searches
    the re-plan added".
    """
    return [
        {
            "mode": spec.mode,
            "query": spec.semantic or " ".join(spec.keywords),
            "filters": {
                "correspondent_id": spec.filters.correspondent_id,
                "document_type_id": spec.filters.document_type_id,
                "tag_ids": list(spec.filters.tag_ids),
                "date_from": spec.filters.date_from,
                "date_to": spec.filters.date_to,
            },
            "rationale": spec.rationale,
        }
        for spec in specs
    ]


def _specs_equal(
    left: tuple[RetrievalSpec, ...],
    right: tuple[RetrievalSpec, ...],
) -> bool:
    """Return True when two resolved spec tuples are equivalent (no-op guard).

    Frozen-dataclass equality compares every field, but ``SearchFilters.tag_ids``
    is an order-sensitive tuple — two re-plans that resolve the same tags in a
    different order are the *same* search. Each spec's ``tag_ids`` is normalised
    to a sorted tuple before comparison so a mere re-ordering reads as a no-op
    (and the pass skips a redundant, billable retrieve + judge).
    """
    if len(left) != len(right):
        return False
    return all(_normalise_spec(a) == _normalise_spec(b) for a, b in zip(left, right))


def _normalise_spec(spec: RetrievalSpec) -> RetrievalSpec:
    """Return *spec* with its filters' ``tag_ids`` sorted, for stable comparison."""
    return replace(
        spec,
        filters=replace(spec.filters, tag_ids=tuple(sorted(spec.filters.tag_ids))),
    )


def _guess_dict(fg: FilterCandidates) -> dict[str, object]:
    """Flatten a :class:`FilterCandidates` to a serialisable dict of guesses."""
    return {
        "correspondent": fg.correspondent,
        "document_type": fg.document_type,
        "tags": list(fg.tags),
        "date_from": fg.date_from,
        "date_to": fg.date_to,
    }


def _dropped_guesses(
    plan: RetrievalPlan,
    specs: tuple[RetrievalSpec, ...],
) -> list[dict[str, object]]:
    """List the name guesses that did not resolve to a taxonomy id, per spec.

    A guess is "dropped" when the plan carried a name (correspondent / document
    type / a tag) but the matching resolved id is ``None`` (or, for tags, the
    resolved id set is smaller than the guess set). Dates are deterministic and
    never reported here. The result is JSON-serialisable primitives.
    """
    dropped: list[dict[str, object]] = []
    for index, (planned, resolved) in enumerate(zip(plan.specs, specs)):
        guess = planned.filter_guess
        names: list[str] = []
        if (
            guess.correspondent is not None
            and resolved.filters.correspondent_id is None
        ):
            names.append(guess.correspondent)
        if (
            guess.document_type is not None
            and resolved.filters.document_type_id is None
        ):
            names.append(guess.document_type)
        # A tag guess is dropped when fewer ids resolved than tags were guessed;
        # the ids are anonymous, so report the count rather than guess which.
        if len(guess.tags) > len(resolved.filters.tag_ids):
            names.extend(guess.tags[len(resolved.filters.tag_ids) :])
        if names:
            dropped.append({"spec_index": index, "names": names})
    return dropped


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
