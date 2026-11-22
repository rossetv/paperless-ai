"""Search-core orchestration: the bounded agentic pipeline.

``SearchCore`` wires the planner, retriever, judge and synthesiser together and
assembles the public :class:`~search.models.SearchResult`. It imports neither
FastAPI nor MCP.

- ``answer(query, ui_filters)`` — plan, retrieve, judge, synthesise, and refine
  while the synthesiser asks for more. Backs ``/api/search`` and the MCP
  ``deep_search`` tool.
- ``retrieve(query, ui_filters)`` — plan-free hybrid retrieval on the raw query
  with zero chat LLM calls. Backs the MCP ``semantic_search`` tool, where the
  calling agent does its own synthesis at no cost to the archive owner.

The per-query LLM-call budget
-----------------------------
The base is one planner call, an optional judge call and one exploratory
synthesise. Each refinement pass costs one re-plan + one synthesise (+ one
re-judge when the judge gate is on), so the bound is ``2 + j + R * (2 + j)``
with ``j`` 1 iff the judge gate is on and ``R`` = ``SEARCH_MAX_REFINEMENTS``
(see :func:`_max_llm_calls`). The refinement count has no hard cap in the UI,
so cost and latency scale with it. The query embedding is not a chat call and
is not counted.

The loop structure bounds the calls; every stage is also recorded through
:class:`_LlmBudget`, which raises :class:`~search.errors.LlmBudgetExceededError`
if a logic regression ever tries an extra call.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING

import structlog

from search.cache import (
    build_cache_key,
    cache_generation,
    get_search_result_cache,
    is_cacheable,
)
from search.errors import LlmBudgetExceededError
from search.judge import RelevanceJudge
from search.models import (
    Answered,
    ClarifyNeeded,
    Cost,
    CostSummary,
    FilterCandidates,
    JudgeCandidate,
    JudgeVerdict,
    NeedsMore,
    NoMatchReason,
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
    raw_rag_plan,
    trivial_plan,
)
from search.prompts import build_planner_taxonomy_block
from search.retriever import NameMatch, _match_name, resolve_specs
from search.relevance import RelevanceThresholds
from search.sources import _paperless_url, _snippet, assemble_sources
from search.text import (
    ADJUSTMENT_LOG_PREFIX_CHARS,
    QUERY_LOG_PREFIX_CHARS,
    is_trivial_query,
)
from search.fetch import assemble_fetched
from search.trace import OnEvent, PhaseRecord, PhaseStart, _Telemetry
from store import StoreError
from store.models import DocumentBrowseQuery, KeywordHit, KeywordPage, SearchFilters

if TYPE_CHECKING:
    from collections.abc import Callable

    from common.config import Settings
    from common.llm import LlmCallUsage
    from common.paperless import PaperlessClient
    from search.cache import _CacheKey
    from search.models import FetchedDocument
    from search.planner import QueryPlanner
    from search.retriever import Retriever
    from search.synthesizer import Synthesizer
    from store.models import FacetSet, FilterCatalog, IndexedDocument
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

# Per-document character cap for the MCP fetch_documents tool (~12k tokens), so
# one fetch of a long document cannot blow the caller's context or the MCP
# transport. Longer content is truncated and flagged.
FETCH_MAX_CHARS = 50_000

# The answer when retrieval finds nothing or the relevance gate rejects the
# signal; both short-circuit before any synthesis call. Shared by every
# no_match path.
_NO_MATCHES_ANSWER = (
    "I couldn't find any documents matching that. "
    "Try rephrasing, or broaden your search."
)

# Fixed answer for the planner's adequacy gate. The model's reason is logged but
# never shown, so the message is stable whichever model phrased the rejection.
_CLARIFY_ANSWER = (
    "That search is a bit too broad for me to answer well. "
    "Add a detail or two, or use the filters to pick a correspondent or document type."
)


class _LlmBudget:
    """A monotonically-increasing counter enforcing the per-query LLM-call limit.

    Every chat call is recorded *before* it is made, so ``record`` can refuse
    one that would breach the limit. ``count`` is calls *attempted*: a stage
    whose models all failed is still counted, so ``SearchStats.llm_calls``
    reports attempts, which equal billable calls only on a fully successful
    query.
    """

    def __init__(self, max_calls: int) -> None:
        self.count = 0
        self.max_calls = max_calls

    def record(self) -> None:
        """Register one LLM chat call; fail loud if the limit is breached.

        A ``raise`` rather than ``assert``, which ``python -O`` would strip.

        Raises:
            LlmBudgetExceededError: Recording this call would exceed the limit.
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

    Carries the resolved pass-1 specs and the facets used to resolve them, so
    the refinement pass can re-plan against the same taxonomy and run its no-op
    guard without a second ``list_facets`` round-trip. ``documents_by_id`` is
    built once here and shared with later phases.
    """

    chunks: list[RetrievedChunk]
    signal: RetrievalSignal
    specs: tuple[RetrievalSpec, ...]
    facets: FacetSet
    documents_by_id: dict[int, IndexedDocument]


class SearchCore:
    """Orchestrates the bounded agentic search pipeline.

    Stages are injected so the pipeline is testable offline with a mock LLM
    client. An instance holds no per-request state, so it is safe to share
    across request threads.
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
        # A search queued under this core can finish after a settings save has
        # replaced it; its answer must not land in the cache built since.
        self._cache_generation = cache_generation()

    @property
    def settings(self) -> Settings:
        """Return the :class:`Settings` this core was built from.

        :mod:`search.routes` reads ``SEARCH_MAX_CONCURRENT`` from it to keep the
        ``/api/search`` semaphore in step with the live configuration.
        """
        return self._settings

    def _relevance_thresholds(self) -> RelevanceThresholds:
        """Build the relevance-badge cut-points from the live settings.

        Read per request so a retune of ``SEARCH_RELEVANCE_TIER_*`` applies on
        the next search without a restart (the core is rebuilt on a
        config-version bump).
        """
        return RelevanceThresholds(
            strong=self._settings.SEARCH_RELEVANCE_TIER_STRONG,
            good=self._settings.SEARCH_RELEVANCE_TIER_GOOD,
            partial=self._settings.SEARCH_RELEVANCE_TIER_PARTIAL,
        )

    def answer(
        self,
        query: str,
        ui_filters: SearchFilters | None = None,
        asker: str | None = None,
        on_event: OnEvent | None = None,
        on_cache_hit: Callable[[], None] | None = None,
    ) -> SearchResult:
        """Run the full pipeline and return a synthesised SearchResult.

        Results go through the process result cache, keyed on the normalised
        query, the UI filters, an index-version signal and the asker; a hit
        makes zero LLM calls. Answered, clarify and no-match results are all
        cached (a no-match is invalidated by the index version moving, not a
        timer); the degraded synthesiser fallback never is. The cache is
        bypassed when the index version cannot be read, and disabled by a
        ``SEARCH_CACHE_TTL_SECONDS`` of 0.

        Args:
            ui_filters: Explicit user-set filters; authoritative, bypassing
                free-text filter resolution.
            asker: Sanitised display name of the requester, so first-person
                references resolve; part of the cache key so users never share
                each other's answers.
            on_event: Fed a :class:`~search.trace.PhaseStart` then a
                :class:`~search.models.PhaseRecord` per executed phase (the
                streaming route). A cache hit emits a single ``cache`` phase.
            on_cache_hit: Called once when the result is served from the cache,
                so a caller charging a token quota charges nothing for it; the
                result's own cost still reports the original spend.
        """
        cache = get_search_result_cache(self._settings.SEARCH_CACHE_TTL_SECONDS)
        # Building the key costs a get_stats() round-trip, so skip it when the
        # cache is off.
        cache_key = (
            self._cache_key(query, ui_filters, asker)
            if self._settings.SEARCH_CACHE_TTL_SECONDS > 0
            and self._cache_generation == cache_generation()
            else None
        )
        if cache_key is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                log.info(
                    "search.cache_hit", query_prefix=query[:QUERY_LOG_PREFIX_CHARS]
                )
                if on_event is not None:
                    self._emit_cache_phase(on_event, cached)
                if on_cache_hit is not None:
                    on_cache_hit()
                return cached

        result = self._answer_uncached(query, ui_filters, asker, on_event=on_event)

        if cache_key is not None and is_cacheable(result):
            cache.put(cache_key, result)
        return result

    @staticmethod
    def _emit_cache_phase(on_event: OnEvent, cached: SearchResult) -> None:
        """Emit the synthetic ``cache`` phase for a cache hit.

        A streamed search still needs a terminal phase. Its detail carries the
        original (now saved) cost so the SPA can show "served from cache
        (saved $X)".
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

        Plan, resolve filters, retrieve (broadening once if empty), judge,
        synthesise, and refine while the synthesiser asks for more and the
        budget allows. Fail-fast gates at the front:

        * degenerate input: a stripped query shorter than
          ``SEARCH_MIN_QUERY_CHARS`` is a clarify with zero LLM calls;
        * adequacy: the planner may return
          :class:`~search.models.ClarifyNeeded` for an obviously vague query;
        * relevance (``SEARCH_GATE_RELEVANCE``): chunks whose best vector
          similarity is below ``SEARCH_RELEVANCE_MIN_SIMILARITY`` *and* that
          have no keyword hit are a no_match. A ``None`` similarity (no vector
          pass ran) always proceeds.
        """
        started = time.monotonic()
        tele = _Telemetry(on_event)
        budget = _LlmBudget(max_calls=_max_llm_calls(self._settings))

        # Degenerate-input guard, before any phase, so the trace is empty.
        if len(query.strip()) < self._settings.SEARCH_MIN_QUERY_CHARS:
            return self._clarify_result(
                "query below SEARCH_MIN_QUERY_CHARS", budget, started, tele
            )

        # Fetched once: the planner sees the real taxonomy names, and the same
        # facets are reused for filter resolution in the retrieve phase.
        facets = self._store_reader.list_facets()
        plan_outcome = self._plan_phase(query, budget, asker, tele, facets)
        if isinstance(plan_outcome, ClarifyNeeded):
            return self._clarify_result(plan_outcome.reason, budget, started, tele)
        plan = plan_outcome

        retrieved = self._retrieve_phase(
            plan, ui_filters, tele, query=query, facets=facets
        )
        chunks, signal = retrieved.chunks, retrieved.signal
        current_specs = retrieved.specs
        # One store read per query, shared by every later phase; refinement
        # tops it up in place with only the genuinely new documents.
        documents_by_id = retrieved.documents_by_id
        if not chunks:
            log.info(
                "search.no_matches",
                query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
            )
            return self._no_match_result(
                plan,
                budget,
                started,
                tele,
                reason="empty_retrieval",
                candidate_count=0,
            )

        if self._settings.SEARCH_GATE_RELEVANCE and self._gate_rejects(
            signal, chunks, tele, retrieved.documents_by_id
        ):
            log.info(
                "search.synth_skipped_no_relevance",
                query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
                best_vector_similarity=signal.best_vector_similarity,
                has_keyword_hit=signal.has_keyword_hit,
            )
            return self._no_match_result(
                plan,
                budget,
                started,
                tele,
                reason="weak_relevance",
                candidate_count=len({c.document_id for c in chunks}),
            )

        # Judge scores accumulate here (and any re-judge updates them) so the
        # final sources rank by relevance.
        judge_scores: dict[int, float] = {}
        today_iso = date.today().isoformat()
        filtered = self._judge_and_filter(
            query,
            chunks,
            budget,
            tele,
            judge_scores,
            documents_by_id,
            asker=asker,
            today=today_iso,
        )
        if filtered is None:
            log.info("search.judge_bailed", query_prefix=query[:QUERY_LOG_PREFIX_CHARS])
            return self._no_match_result(
                plan,
                budget,
                started,
                tele,
                reason="judge_rejected",
                candidate_count=len({c.document_id for c in chunks}),
            )
        chunks = filtered

        max_refinements = self._settings.SEARCH_MAX_REFINEMENTS
        # With no refinement allowed nothing could act on a needs-more outcome,
        # so the only synthesis must answer.
        outcome = self._synthesise(
            query,
            chunks,
            mode="final" if max_refinements <= 0 else "exploratory",
            budget=budget,
            asker=asker,
            tele=tele,
            documents_by_id=documents_by_id,
        )

        # Intermediate passes stay "exploratory" (may ask for more); the last
        # allowed pass runs in "final" mode (must answer or say not found), so
        # the loop always ends with an Answered outcome.
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
                judge_scores=judge_scores,
                documents_by_id=documents_by_id,
            )
            refinements += 1
        refined = refinements > 0

        answer_text = outcome.answer if isinstance(outcome, Answered) else ""
        sources = assemble_sources(
            chunks,
            self._store_reader,
            self._settings.PAPERLESS_PUBLIC_URL,
            self._relevance_thresholds(),
            judge_scores,
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

        None makes ``answer`` bypass the cache: a search must never fail
        because the cache could not key itself.
        """
        index_version = self._index_version()
        if index_version is None:
            return None
        return build_cache_key(
            query=query, filters=ui_filters, index_version=index_version, asker=asker
        )

    def _index_version(self) -> str | None:
        """Return ``document_count:chunk_count:latest_indexed_at`` as the cache version.

        The counts move when a document is indexed, re-chunked or pruned.
        ``MAX(indexed_at)`` catches an in-place re-index (corrected OCR, edited
        tags) that leaves both counts unchanged. It must not be
        ``last_reconcile_at``, which is rewritten by every reconcile cycle,
        including no-op ones, and would evict valid entries each cycle.

        Returns None on a store read failure, so the caller bypasses the cache.
        """
        try:
            stats = self._store_reader.get_stats()
        except StoreError as exc:
            log.debug("search.cache_version_unavailable", error=str(exc))
            return None
        content_signal = stats.latest_indexed_at or "none"
        return f"{stats.document_count}:{stats.chunk_count}:{content_signal}"

    def retrieve(
        self,
        query: str,
        ui_filters: SearchFilters | None = None,
        on_event: OnEvent | None = None,
    ) -> SearchResult:
        """Plan-free hybrid retrieval — ranked sources, zero chat LLM calls.

        Backs the MCP ``semantic_search`` tool. A deterministic hybrid plan
        (:func:`~search.refinement.raw_rag_plan`) replaces the planner, and the
        only model call is the query embedding. The result's ``answer`` is
        empty.

        The degenerate-input guard still applies; the relevance gate does not,
        since the result is advisory.
        """
        started = time.monotonic()
        tele = _Telemetry(on_event)
        budget = _LlmBudget(max_calls=_max_llm_calls(self._settings))

        if len(query.strip()) < self._settings.SEARCH_MIN_QUERY_CHARS:
            return self._clarify_result(
                "query below SEARCH_MIN_QUERY_CHARS", budget, started, tele
            )

        facets = self._store_reader.list_facets()
        plan = raw_rag_plan(query)
        retrieved = self._retrieve_phase(
            plan, ui_filters, tele, query=query, facets=facets
        )
        sources = assemble_sources(
            retrieved.chunks,
            self._store_reader,
            self._settings.PAPERLESS_PUBLIC_URL,
            self._relevance_thresholds(),
        )
        return self._build_result(
            "", sources, plan, budget, started, tele, refined=False
        )

    def list_filters(self) -> FilterCatalog:
        """Return every filter value (with doc counts) + the date range. No LLM.

        Backs the MCP ``list_filters`` tool, so a calling model can discover
        the exact ids to filter on.
        """
        return self._store_reader.list_filters_with_counts()

    def keyword_search(
        self,
        query: str | None,
        ui_filters: SearchFilters | None,
        limit: int,
        offset: int,
    ) -> KeywordPage:
        """Free keyword/filter document search. No LLM, no embedding.

        With a *query*: FTS5 search over chunk content, grouped to ranked
        documents. Without one: a filter-only browse, newest first, covering
        "every document tagged X / from correspondent Y".
        """
        filters = ui_filters or SearchFilters(
            date_from=None,
            date_to=None,
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(),
        )
        if query and query.strip():
            return self._store_reader.keyword_document_search(
                tuple(query.split()), filters, limit, offset
            )
        browse = DocumentBrowseQuery(
            text=None,
            date_from=filters.date_from,
            date_to=filters.date_to,
            correspondent_id=filters.correspondent_id,
            document_type_id=filters.document_type_id,
            tag_ids=tuple(filters.tag_ids),
            sort="created",
            descending=True,
            offset=offset,
            limit=limit,
        )
        page = self._store_reader.list_documents(browse)
        hits = tuple(
            KeywordHit(document=doc, snippet=None, rank=0.0) for doc in page.documents
        )
        return KeywordPage(hits=hits, total=page.total, offset=offset, limit=limit)

    def fetch_documents(
        self,
        ids: list[int],
        paperless_client: PaperlessClient,
    ) -> list[FetchedDocument]:
        """Full OCR text (capped) for a handful of documents by id. No LLM.

        Backs the MCP ``fetch_documents`` tool; truncates at
        :data:`FETCH_MAX_CHARS`. The caller owns *paperless_client*'s lifecycle.
        """
        return assemble_fetched(
            ids,
            paperless_client,
            self._store_reader,
            self._settings.PAPERLESS_PUBLIC_URL,
            FETCH_MAX_CHARS,
        )

    def _plan_phase(
        self,
        query: str,
        budget: _LlmBudget,
        asker: str | None,
        tele: _Telemetry,
        facets: FacetSet,
    ) -> RetrievalPlan | ClarifyNeeded:
        """Run the plan stage, emitting the ``plan`` phase with its detail."""
        tele.start("plan", "Planning the query")
        started = time.monotonic()
        sink: list[LlmCallUsage] = []
        skipped_trivial = (
            self._settings.SEARCH_SKIP_PLANNER_FOR_TRIVIAL and is_trivial_query(query)
        )
        outcome = self._plan(query, budget, asker, usage_sink=sink, facets=facets)
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
        *,
        facets: FacetSet,
    ) -> RetrievalPlan | ClarifyNeeded:
        """Run the planner, or skip it for a trivial query.

        With ``SEARCH_SKIP_PLANNER_FOR_TRIVIAL`` set, a short, signal-free
        keyword lookup uses the trivial plan instead of an LLM call; retrieval
        still runs vector + FTS on the raw query, so nothing is lost.

        Returns ``ClarifyNeeded`` when the planner's adequacy gate fires.
        """
        if self._settings.SEARCH_SKIP_PLANNER_FOR_TRIVIAL and is_trivial_query(query):
            log.info(
                "search.planner_skipped_trivial",
                query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
            )
            return trivial_plan(query)
        budget.record()
        taxonomy_block = build_planner_taxonomy_block(
            facets, self._settings.SEARCH_PLANNER_TAXONOMY_LIMIT
        )
        return self._planner.plan(
            query, asker=asker, usage_sink=usage_sink, taxonomy_block=taxonomy_block
        )

    def _retrieve_phase(
        self,
        plan: RetrievalPlan,
        ui_filters: SearchFilters | None,
        tele: _Telemetry,
        *,
        query: str,
        facets: FacetSet,
    ) -> _RetrievalPhaseResult:
        """Resolve the plan's specs then retrieve, emitting both phases.

        The raw *query* feeds :func:`~search.retriever.resolve_specs`'s date
        safety net: if no spec carries a date filter but the query names an
        explicit period, a date-scoped spec is appended. ``max_specs`` enables
        the unfiltered recall twin, so a bad filter can never silently exclude
        the answer.
        """
        today = date.today()
        specs = resolve_specs(
            plan,
            facets,
            ui_filters=ui_filters,
            today=today,
            query=query,
            max_specs=self._settings.SEARCH_PLANNER_MAX_SPECS,
        )
        self._emit_resolve_phase(plan, specs, facets, tele)

        tele.start("retrieve", "Retrieving documents")
        started = time.monotonic()
        chunks, signal, broadened = self._retrieve_with_broaden(
            plan, specs, facets, today
        )
        doc_ids = {c.document_id for c in chunks}
        documents_by_id = {
            doc.id: doc for doc in self._store_reader.get_documents(doc_ids)
        }
        tele.done(
            "retrieve",
            "Retrieving documents",
            {
                "chunk_count": len(chunks),
                "doc_count": len(doc_ids),
                "broadened": broadened,
                "chunks": _trace_chunks(chunks, documents_by_id),
            },
            usage_sink=[],
            started=started,
        )
        return _RetrievalPhaseResult(
            chunks=chunks,
            signal=signal,
            specs=specs,
            facets=facets,
            documents_by_id=documents_by_id,
        )

    @staticmethod
    def _emit_resolve_phase(
        plan: RetrievalPlan,
        specs: tuple[RetrievalSpec, ...],
        facets: FacetSet,
        tele: _Telemetry,
    ) -> None:
        """Emit the non-LLM ``resolve`` phase: resolved filter names/methods + drop reasons.

        ``dropped`` lists each name guess that did not resolve (``method`` in
        :data:`_DROPPED_METHODS`), with the competing candidate names for the
        ambiguous and near-miss cases.

        The methods are recomputed via :func:`~search.retriever._match_name`
        so this does not depend on ``resolve_specs`` returning its
        intermediate results.
        """
        tele.start("resolve", "Resolving filters")
        started = time.monotonic()
        tele.done(
            "resolve",
            "Resolving filters",
            {
                "resolved": [
                    _resolved_spec_detail(
                        index, spec, plan.specs[index].filter_guess, facets
                    )
                    for index, spec in enumerate(specs)
                    if index < len(plan.specs)
                ],
                "dropped": _dropped_guesses(plan, specs, facets),
            },
            usage_sink=[],
            started=started,
        )

    def _gate_rejects(
        self,
        signal: RetrievalSignal,
        chunks: list[RetrievedChunk],
        tele: _Telemetry,
        documents_by_id: dict[int, IndexedDocument] | None = None,
    ) -> bool:
        """Run the relevance gate, emitting the ``gate`` phase.

        The gate is one aggregate decision over the retrieval signal; it never
        drops individual documents (the judge does that). Returns True when the
        signal is too weak to synthesise from.
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
                "documents": _gate_documents(chunks, documents_by_id or {}),
            },
            usage_sink=[],
            started=started,
        )
        return rejected

    def _retrieve_with_broaden(
        self,
        plan: RetrievalPlan,
        specs: tuple[RetrievalSpec, ...],
        facets: FacetSet,
        today: date,
    ) -> tuple[list[RetrievedChunk], RetrievalSignal, bool]:
        """Retrieve for the resolved *specs*; broaden and retry once if empty.

        A mis-resolved or hallucinated filter is the most common cause of an
        otherwise answerable query returning nothing, so the retry drops every
        spec's filters, including UI-set ones.

        Returns:
            ``(chunks, signal, broadened)``; *broadened* is True iff the
            filter-dropped pass ran.
        """
        chunks, signal = self._retriever.retrieve(specs)
        if chunks:
            return chunks, signal, False

        broadened_specs = resolve_specs(
            broaden_plan(plan), facets, ui_filters=None, today=today
        )
        log.info("search.retrieval_broadened")
        chunks, signal = self._retriever.retrieve(broadened_specs)
        return chunks, signal, True

    def _judge_candidates(
        self,
        chunks: list[RetrievedChunk],
        *,
        documents_by_id: dict[int, IndexedDocument],
    ) -> list[JudgeCandidate]:
        """Reduce chunks to one document-level candidate each, with metadata.

        The snippet is the document's highest-``rrf_score`` chunk. The title,
        date, correspondent and type let the judge score relevance to the asked
        period or entity, not just the snippet. A document pruned between
        retrieval and the judge keeps a snippet-only candidate.
        """
        best_score: dict[int, float] = {}
        snippet: dict[int, str] = {}
        for chunk in chunks:
            current = best_score.get(chunk.document_id)
            if current is None or chunk.rrf_score > current:
                best_score[chunk.document_id] = chunk.rrf_score
                snippet[chunk.document_id] = _snippet(chunk.text)
        candidates: list[JudgeCandidate] = []
        for document_id in best_score:
            indexed = documents_by_id.get(document_id)
            candidates.append(
                JudgeCandidate(
                    document_id=document_id,
                    snippet=snippet[document_id],
                    title=indexed.title if indexed is not None else None,
                    created=indexed.created if indexed is not None else None,
                    correspondent=(
                        indexed.correspondent if indexed is not None else None
                    ),
                    document_type=(
                        indexed.document_type if indexed is not None else None
                    ),
                )
            )
        return candidates

    def _judge_and_filter(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        budget: _LlmBudget,
        tele: _Telemetry,
        judge_scores: dict[int, float] | None,
        documents_by_id: dict[int, IndexedDocument],
        *,
        asker: str | None = None,
        today: str | None = None,
    ) -> list[RetrievedChunk] | None:
        """Judge the retrieved documents; return filtered chunks, or None to bail.

        Returns chunks unchanged when the judge is disabled. Bails (None) only
        when a non-degraded verdict drops every document; fails open (all
        chunks) if filtering would otherwise keep nothing.

        For a re-judge over merged chunks the caller must already have merged
        the new documents into *documents_by_id*. *judge_scores*, when given,
        receives each document's score (a re-judge overwrites earlier ones).
        """
        if not self._settings.SEARCH_GATE_JUDGE:
            return chunks
        candidates = self._judge_candidates(chunks, documents_by_id=documents_by_id)
        tele.start("judge", "Judging relevance")
        started = time.monotonic()
        sink: list[LlmCallUsage] = []
        budget.record()
        verdict = self._judge.judge(
            query, candidates, asker=asker, today=today, usage_sink=sink
        )
        kept_ids = _surviving_ids(verdict)
        bailed = not kept_ids and not verdict.degraded
        if judge_scores is not None:
            for dv in verdict.verdicts:
                judge_scores[dv.document_id] = dv.score
        public_url = self._settings.PAPERLESS_PUBLIC_URL
        tele.done(
            "judge",
            "Judging relevance",
            {
                "degraded": verdict.degraded,
                "bailed": bailed,
                "verdicts": [
                    {
                        "doc_id": dv.document_id,
                        "title": _title_for(documents_by_id, dv.document_id),
                        "keep": dv.keep,
                        "reason": dv.reason,
                        "score": dv.score,
                        "paperless_url": _paperless_url(public_url, dv.document_id),
                    }
                    for dv in verdict.verdicts
                ],
            },
            usage_sink=sink,
            started=started,
        )
        if bailed:
            return None
        kept = [c for c in chunks if c.document_id in kept_ids]
        if not kept:
            return chunks
        if not verdict.degraded:
            dropped = sorted({c.document_id for c in chunks} - kept_ids)
            if dropped:
                log.info(
                    "search.judge_filtered",
                    query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
                    kept=len(kept_ids),
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
        documents_by_id: dict[int, IndexedDocument],
    ) -> Answered | NeedsMore:
        """Run one synthesiser LLM call, emit the ``synthesise`` phase, budget it.

        Emitted once per call: the exploratory pass and each refinement pass.
        """
        tele.start("synthesise", "Synthesising the answer")
        started = time.monotonic()
        sink: list[LlmCallUsage] = []
        budget.record()
        outcome = self._synthesizer.synthesise(
            query,
            chunks,
            mode=mode,
            asker=asker,
            usage_sink=sink,
            documents_by_id=_synth_metadata(chunks, documents_by_id),
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
        judge_scores: dict[int, float],
        documents_by_id: dict[int, IndexedDocument],
    ) -> tuple[Answered | NeedsMore, list[RetrievedChunk], tuple[RetrievalSpec, ...]]:
        """Run one refinement pass driven by the synthesiser's gap hint.

        The pass re-plans: the planner is asked for different specs targeting
        ``needs_more.adjustment``, given *prior_specs* and the documents found.
        If the re-plan resolves to the same specs, or returns
        :class:`ClarifyNeeded` (refinement never asks the user to clarify), the
        pass skips the redundant, billable retrieve + judge and just
        synthesises once on the existing evidence. Otherwise it retrieves,
        merges, re-judges and re-synthesises in *mode*.

        Returns:
            The synthesiser outcome, the chunks used as its context, and the
            specs now in effect (*prior_specs* on a no-op or clarify), so the
            next pass re-plans against what was actually tried.
        """
        log.info(
            "search.refined",
            query_prefix=query[:QUERY_LOG_PREFIX_CHARS],
            adjustment=needs_more.adjustment[:ADJUSTMENT_LOG_PREFIX_CHARS],
        )
        prior_findings = _finding_titles(previous_chunks, documents_by_id)
        replan_outcome = self._replan_phase(
            query,
            needs_more.adjustment,
            prior_specs,
            prior_findings,
            budget,
            asker,
            tele,
            facets,
        )

        if isinstance(replan_outcome, ClarifyNeeded):
            self._emit_refine_marker(
                needs_more.adjustment, [], len(previous_chunks), noop=True, tele=tele
            )
            outcome = self._synthesise(
                query,
                previous_chunks,
                mode=mode,
                budget=budget,
                asker=asker,
                tele=tele,
                documents_by_id=documents_by_id,
            )
            return outcome, previous_chunks, prior_specs

        new_specs = resolve_specs(
            replan_outcome,
            facets,
            ui_filters=ui_filters,
            today=date.today(),
            max_specs=self._settings.SEARCH_PLANNER_MAX_SPECS,
        )

        if _specs_equal(new_specs, prior_specs):
            self._emit_refine_marker(
                needs_more.adjustment, [], len(previous_chunks), noop=True, tele=tele
            )
            outcome = self._synthesise(
                query,
                previous_chunks,
                mode=mode,
                budget=budget,
                asker=asker,
                tele=tele,
                documents_by_id=documents_by_id,
            )
            return outcome, previous_chunks, prior_specs

        new_chunks, _signal = self._retriever.retrieve(new_specs)
        merged = merge_chunks(previous_chunks, new_chunks)
        self._merge_documents(documents_by_id, new_chunks)
        self._emit_refine_marker(
            needs_more.adjustment,
            _spec_detail_for_resolved(new_specs),
            len(previous_chunks),
            noop=False,
            tele=tele,
        )
        # A bail mid-refine falls back to the merged chunks: there was already
        # relevant evidence, so never downgrade to no_match.
        judged = self._judge_and_filter(
            query,
            merged,
            budget,
            tele,
            judge_scores,
            documents_by_id,
            asker=asker,
            today=date.today().isoformat(),
        )
        kept = judged if judged is not None else merged
        outcome = self._synthesise(
            query,
            kept,
            mode=mode,
            budget=budget,
            asker=asker,
            tele=tele,
            documents_by_id=documents_by_id,
        )
        return outcome, kept, new_specs

    def _merge_documents(
        self,
        documents_by_id: dict[int, IndexedDocument],
        chunks: list[RetrievedChunk],
    ) -> None:
        """Fetch into *documents_by_id*, in place, any documents it lacks."""
        missing = sorted({c.document_id for c in chunks} - documents_by_id.keys())
        if not missing:
            return
        for doc in self._store_reader.get_documents(missing):
            documents_by_id[doc.id] = doc

    def _replan_phase(
        self,
        query: str,
        hint: str,
        prior_specs: tuple[RetrievalSpec, ...],
        prior_findings: tuple[str, ...],
        budget: _LlmBudget,
        asker: str | None,
        tele: _Telemetry,
        facets: FacetSet,
    ) -> RetrievalPlan | ClarifyNeeded:
        """Run the re-plan stage, emitting the ``replan`` phase with its usage.

        The re-plan's tokens are attributed here, not to the ``refine`` marker.
        """
        tele.start("replan", "Re-planning")
        started = time.monotonic()
        sink: list[LlmCallUsage] = []
        budget.record()
        taxonomy_block = build_planner_taxonomy_block(
            facets, self._settings.SEARCH_PLANNER_TAXONOMY_LIMIT
        )
        outcome = self._planner.replan(
            query,
            hint=hint,
            prior_specs=prior_specs,
            prior_findings=prior_findings,
            asker=asker,
            usage_sink=sink,
            taxonomy_block=taxonomy_block,
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

        No tokens: the re-plan and synthesise phases carry their own.
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

        The trace and cost summary ride on :class:`SearchStats` so they are
        cached and reach every consumer.
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
        *,
        reason: NoMatchReason,
        candidate_count: int,
    ) -> SearchResult:
        """Build the no-hits SearchResult — no sources, no synthesis call.

        Shared by empty retrieval, the relevance-gate rejection and the judge
        bailing on every candidate; ``reason`` lets the UI tailor its message.
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
            no_match_reason=reason,
            candidate_count=candidate_count,
        )

    def _clarify_result(
        self,
        reason: str,
        budget: _LlmBudget,
        started: float,
        tele: _Telemetry,
    ) -> SearchResult:
        """Build the clarify SearchResult.

        *reason* is only logged; the user sees the fixed ``_CLARIFY_ANSWER``.
        """
        log.info(
            "search.clarify_needed",
            reason=reason,
        )
        # No retrieval ran, but callers always get a non-null plan.
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


def _elapsed_ms(started: float) -> int:
    """Return whole milliseconds elapsed since the monotonic timestamp *started*."""
    return int((time.monotonic() - started) * 1000)


def _surviving_ids(verdict: JudgeVerdict) -> frozenset[int]:
    """Return the document ids whose verdict is ``keep=True``.

    ``keep`` is the sole gate; ``score`` only ranks sources.
    """
    return frozenset(v.document_id for v in verdict.verdicts if v.keep)


def _title_for(
    documents_by_id: dict[int, IndexedDocument], document_id: int
) -> str | None:
    """Return *document_id*'s indexed title, or None when it is not in the look-up."""
    indexed = documents_by_id.get(document_id)
    return indexed.title if indexed is not None else None


def _synth_metadata(
    chunks: list[RetrievedChunk],
    documents_by_id: dict[int, IndexedDocument],
) -> dict[int, tuple[str | None, str | None]]:
    """Build the ``{document_id: (title, created)}`` map for the synthesiser.

    A document missing from the look-up (pruned mid-query) is left out, and
    the synthesiser falls back to its bare ``[id]`` label.
    """
    return {
        document_id: (doc.title, doc.created)
        for document_id in {c.document_id for c in chunks}
        if (doc := documents_by_id.get(document_id)) is not None
    }


def _finding_titles(
    chunks: list[RetrievedChunk],
    documents_by_id: dict[int, IndexedDocument],
) -> tuple[str, ...]:
    """Return the titles of the documents in *chunks*, for the re-plan turn.

    Untitled or unknown documents are dropped. Order follows first appearance
    in *chunks* (descending fused score), so the strongest findings lead.
    """
    seen: list[int] = []
    for chunk in chunks:
        if chunk.document_id not in seen:
            seen.append(chunk.document_id)
    titles: list[str] = []
    for document_id in seen:
        doc = documents_by_id.get(document_id)
        if doc is not None and doc.title:
            titles.append(doc.title)
    return tuple(titles)


def _max_llm_calls(settings: Settings) -> int:
    """Return the per-query LLM-call upper bound for ``_LlmBudget``.

    ``2 + j + R * (2 + j)``: one planner call and one exploratory synthesise,
    plus per refinement pass a re-plan and a synthesise; ``j`` adds a judge call
    to each when ``SEARCH_GATE_JUDGE`` is on. A no-op refinement pass costs
    less, so this is an upper bound, not an exact count.
    """
    judge_call = 1 if settings.SEARCH_GATE_JUDGE else 0
    refinements = settings.SEARCH_MAX_REFINEMENTS
    return 2 + judge_call + refinements * (2 + judge_call)


def _cost_dict(cs: CostSummary) -> dict[str, object]:
    """Flatten a :class:`CostSummary` to a JSON-friendly dict for a phase detail."""
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

    Falls back to the raw *query* (a clarify, or a keyword-only plan) so the
    SPA always has a non-empty label.
    """
    if plan is None:
        return query
    for spec in plan.specs:
        if spec.semantic:
            return spec.semantic
    return query


def _filter_detail(plan: RetrievalPlan | None) -> dict[str, object]:
    """Build the plan phase's ``filters`` detail from the plan's filter guesses.

    Reports the free-text guesses, not resolved ids (that is the ``resolve``
    phase). Across specs the first non-None correspondent, document type and
    date bound wins and tags are unioned; empty guesses are omitted.
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
    """Build the plan phase's ``specs`` detail — one entry per planned spec."""
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
    """Render resolved specs for the ``refine`` phase's ``new_specs`` detail."""
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
    """Return True when two resolved spec tuples are search-equivalent.

    ``rationale`` is excluded: the re-plan rewrites it every call, so including
    it would stop the no-op guard from ever firing.
    """
    if len(left) != len(right):
        return False
    return all(_spec_search_key(a) == _spec_search_key(b) for a, b in zip(left, right))


def _spec_search_key(
    spec: RetrievalSpec,
) -> tuple[str, str | None, tuple[str, ...], object]:
    """Return a comparable key for *spec*, ignoring keyword/tag order and rationale."""
    normalised_filters = replace(
        spec.filters, tag_ids=tuple(sorted(spec.filters.tag_ids))
    )
    return (
        spec.mode,
        spec.semantic,
        tuple(sorted(spec.keywords)),
        normalised_filters,
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


def _resolved_spec_detail(
    spec_index: int,
    spec: RetrievalSpec,
    guess: FilterCandidates,
    facets: FacetSet,
) -> dict[str, object]:
    """Build the ``resolved[i]`` trace entry for one spec.

    The applied id comes from the spec's filters, not the raw match, because a
    UI filter can override the planner's guess.
    """
    corr_detail: dict[str, object] | None = None
    if guess.correspondent is not None:
        m = _match_name(guess.correspondent, facets.correspondents)
        applied_id = spec.filters.correspondent_id
        if applied_id is not None:
            name = next(
                (e.name for e in facets.correspondents if e.id == applied_id), None
            )
            corr_detail = {"id": applied_id, "name": name, "method": m.method}

    dtype_detail: dict[str, object] | None = None
    if guess.document_type is not None:
        m = _match_name(guess.document_type, facets.document_types)
        applied_id = spec.filters.document_type_id
        if applied_id is not None:
            name = next(
                (e.name for e in facets.document_types if e.id == applied_id), None
            )
            dtype_detail = {"id": applied_id, "name": name, "method": m.method}

    tag_details: list[dict[str, object]] = []
    applied_tag_ids = set(spec.filters.tag_ids)
    for tag_guess in guess.tags:
        m = _match_name(tag_guess, facets.tags)
        if m.id is not None and m.id in applied_tag_ids:
            name = next((e.name for e in facets.tags if e.id == m.id), None)
            tag_details.append({"id": m.id, "name": name, "method": m.method})

    return {
        "spec_index": spec_index,
        "correspondent": corr_detail,
        "document_type": dtype_detail,
        "tags": tag_details,
        "date_from": spec.filters.date_from,
        "date_to": spec.filters.date_to,
    }


def _drop_entry(
    spec_index: int, field: str, name: str, match: NameMatch
) -> dict[str, object]:
    """Build one ``dropped[i]`` trace entry for a guess that did not resolve."""
    return {
        "spec_index": spec_index,
        "field": field,
        "name": name,
        "reason": match.method,
        "candidates": list(match.candidates),
    }


# ``_match_name`` methods meaning a guess did not resolve to a filter.
_DROPPED_METHODS = frozenset({"none", "ambiguous", "near_miss"})


def _dropped_guesses(
    plan: RetrievalPlan,
    specs: tuple[RetrievalSpec, ...],
    facets: FacetSet,
) -> list[dict[str, object]]:
    """List the name guesses that did not resolve, with reason and candidates.

    One entry per dropped tag. Dates are deterministic and never reported here.
    """
    dropped: list[dict[str, object]] = []
    for spec_index, (planned, _resolved) in enumerate(zip(plan.specs, specs)):
        guess = planned.filter_guess
        if guess.correspondent is not None:
            m = _match_name(guess.correspondent, facets.correspondents)
            if m.method in _DROPPED_METHODS:
                dropped.append(
                    _drop_entry(spec_index, "correspondent", guess.correspondent, m)
                )
        if guess.document_type is not None:
            m = _match_name(guess.document_type, facets.document_types)
            if m.method in _DROPPED_METHODS:
                dropped.append(
                    _drop_entry(spec_index, "document_type", guess.document_type, m)
                )
        for tag_guess in guess.tags:
            m = _match_name(tag_guess, facets.tags)
            if m.method in _DROPPED_METHODS:
                dropped.append(_drop_entry(spec_index, "tags", tag_guess, m))
    return dropped


_TRACE_SNIPPET_CHARS = 160


def _trace_snippet(text: str) -> str:
    """Return a whitespace-collapsed snippet capped at :data:`_TRACE_SNIPPET_CHARS`.

    Tighter than the source-card snippet because the trace lists every chunk.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= _TRACE_SNIPPET_CHARS:
        return collapsed
    return collapsed[:_TRACE_SNIPPET_CHARS].rstrip() + "…"


def _trace_chunks(
    chunks: list[RetrievedChunk],
    documents_by_id: dict[int, IndexedDocument],
) -> list[dict[str, object]]:
    """Serialise *chunks* for the retrieve-phase trace detail.

    Sorted by ``vector_similarity`` descending, ``None`` last. ``snippet`` is
    the inline preview; ``text`` is the full chunk for the SPA's popover.
    """

    def _sort_key(c: RetrievedChunk) -> tuple[int, float]:
        if c.vector_similarity is None:
            return (1, 0.0)
        return (0, -c.vector_similarity)

    sorted_chunks = sorted(chunks, key=_sort_key)
    return [
        {
            "chunk_id": c.chunk_id,
            "document_id": c.document_id,
            "title": _title_for(documents_by_id, c.document_id)
            or f"Document {c.document_id}",
            "snippet": _trace_snippet(c.text),
            "text": " ".join(c.text.split()),
            "vector_similarity": c.vector_similarity,
        }
        for c in sorted_chunks
    ]


def _gate_documents(
    chunks: list[RetrievedChunk],
    documents_by_id: dict[int, IndexedDocument],
) -> list[dict[str, object]]:
    """Serialise per-document best similarity for the gate-phase trace detail.

    One row per document, sorted by best similarity descending. Documents with
    no similarity on any chunk are left out.
    """
    best: dict[int, float] = {}
    for c in chunks:
        if c.vector_similarity is not None:
            current = best.get(c.document_id)
            if current is None or c.vector_similarity > current:
                best[c.document_id] = c.vector_similarity

    # Sorted before building the dicts so the key is a float, not ``object``.
    ordered = sorted(best.items(), key=lambda item: item[1], reverse=True)
    return [
        {
            "document_id": doc_id,
            "title": _title_for(documents_by_id, doc_id) or f"Document {doc_id}",
            "best_similarity": sim,
        }
        for doc_id, sim in ordered
    ]


def _is_irrelevant(signal: RetrievalSignal, *, min_similarity: float) -> bool:
    """Return True when the retrieval signal is too weak to be worth synthesising.

    Rejects only when the best vector similarity is below *min_similarity* and
    there is no keyword hit. An unknown similarity (no vector results) is not
    evidence of irrelevance, so it never rejects. A *min_similarity* of ``0.0``
    never rejects.
    """
    if signal.best_vector_similarity is None:
        return False
    return signal.best_vector_similarity < min_similarity and not signal.has_keyword_hit


def _cited_sources(
    sources: tuple[SourceDocument, ...],
    outcome: Answered | NeedsMore,
) -> tuple[SourceDocument, ...]:
    """Narrow assembled sources to the documents the answer actually cited.

    The frontend resolves each ``[n]`` marker against ``sources``, so an
    uncited document is noise. Rank order is kept. With no usable citations
    (a :class:`NeedsMore`, a degraded answer, or none cited) every retrieved
    source is returned, so the answer still shows its supporting documents.
    """
    if not isinstance(outcome, Answered) or not outcome.citations:
        return sources
    cited_ids = set(outcome.citations)
    cited = tuple(source for source in sources if source.document_id in cited_ids)
    # Every cited id hallucinated: show the retrieved set, not nothing.
    return cited if cited else sources
