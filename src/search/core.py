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

The hard LLM-call ceiling
-------------------------
Spec §6.3 and CODE_GUIDELINES §14.3 mandate a guaranteed ceiling of **three**
LLM (chat) calls per query: one planner call plus at most two synthesiser
calls.  The query embedding is not a chat call and is not counted (spec §6.5).

The ceiling is enforced two ways, belt and braces:

1. *Structurally* — ``answer`` makes the planner call once, the exploratory
   synthesise once, and the refinement's final synthesise at most once; there
   is no loop that can issue a fourth call.
2. *Defensively* — every LLM stage is invoked through :class:`_LlmBudget`,
   whose ``record`` increments a counter and asserts it never exceeds
   ``_MAX_LLM_CALLS``.  A logic regression that tried a fourth call would fail
   loudly here rather than silently overspending (CODE_GUIDELINES §1.11).

Allowed deps: search (models, planner, retriever, synthesizer, refinement),
    store (reader, models), common.config.
Forbidden: no FastAPI, no MCP SDK, no sqlite3, no direct LLM/HTTP calls.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from search.models import (
    Answered,
    NeedsMore,
    QueryPlan,
    RetrievedChunk,
    SearchResult,
    SearchStats,
    SourceDocument,
)
from search.refinement import adjust_plan, broaden_plan
from search.retriever import resolve_filters
from store.models import IndexedDocument

if TYPE_CHECKING:
    from common.config import Settings
    from search.planner import QueryPlanner
    from search.retriever import Retriever
    from search.synthesizer import Synthesizer
    from store.reader import SearchFilters, StoreReader

log = structlog.get_logger(__name__)

# The guaranteed per-query LLM-call ceiling (spec §6.3, CODE_GUIDELINES §14.3):
# one planner call plus at most two synthesiser calls.  Raising this is a
# security-review point — it bounds per-request cost on a billable endpoint.
_MAX_LLM_CALLS = 3

# The maximum number of characters of chunk text shown as a source snippet in
# the UI.  A snippet is a preview, not the whole chunk; ~280 chars is roughly
# three lines and enough to judge relevance.
_SNIPPET_MAX_CHARS = 280

# Shown as the answer when retrieval yields nothing (spec §6.3): a no-hits
# query short-circuits before any synthesis call, so there is no model prose.
_NO_MATCHES_ANSWER = (
    "No matching documents were found in the archive for this query."
)


class _LlmBudget:
    """A monotonically-increasing counter enforcing the 3-LLM-call ceiling.

    Every LLM chat call in the pipeline is recorded here before it is made.
    ``record`` asserts the running total never exceeds ``_MAX_LLM_CALLS`` — the
    defensive half of the ceiling guarantee (see the module docstring).  The
    final ``count`` is the true number of calls reported in ``SearchStats``.
    """

    def __init__(self) -> None:
        self.count = 0

    def record(self) -> None:
        """Register one LLM chat call; fail loud if the ceiling is breached.

        Raises:
            AssertionError: If recording this call would exceed the hard
                ceiling of three LLM calls per query.  This is unreachable by
                ``SearchCore``'s own loop logic; it guards against a future
                regression silently overspending (CODE_GUIDELINES §1.11).
        """
        self.count += 1
        assert self.count <= _MAX_LLM_CALLS, (
            f"LLM-call ceiling breached: {self.count} calls made, "
            f"the hard limit is {_MAX_LLM_CALLS} (spec §6.3)."
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
            ``PAPERLESS_URL`` are read.
        store_reader: The read-side store interface, for facets and document
            look-ups during source assembly.
        planner: The query-planning stage (LLM call #1).
        retriever: The hybrid retrieval stage (no LLM call).
        synthesizer: The answer-synthesis stage (LLM calls #2 and #3).
    """

    def __init__(
        self,
        settings: Settings,
        store_reader: StoreReader,
        planner: QueryPlanner,
        retriever: Retriever,
        synthesizer: Synthesizer,
    ) -> None:
        self._settings = settings
        self._store_reader = store_reader
        self._planner = planner
        self._retriever = retriever
        self._synthesizer = synthesizer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def answer(
        self,
        query: str,
        ui_filters: SearchFilters | None = None,
    ) -> SearchResult:
        """Run the full pipeline and return a synthesised SearchResult.

        Executes the hard-bounded loop of spec §6.3: plan, resolve filters,
        retrieve, broaden-and-retry once if retrieval is empty, synthesise
        once, and — if the synthesiser asks for more and the refinement budget
        allows — adjust, retrieve again, merge, and synthesise a final time.

        At most three LLM calls are ever made (see the module docstring).

        Args:
            query: The raw user search query.
            ui_filters: Explicit user-set filters; when provided they are
                authoritative and bypass free-text filter resolution.

        Returns:
            A SearchResult with the synthesised answer, ranked source
            documents, the query plan, and execution statistics.
        """
        started = time.monotonic()
        budget = _LlmBudget()

        plan = self._plan(query, budget)
        chunks = self._retrieve_with_broaden(plan, ui_filters)

        if not chunks:
            log.info("search.no_matches", query_prefix=query[:60])
            return self._no_match_result(plan, budget, started)

        outcome = self._synthesise(query, chunks, mode="exploratory", budget=budget)
        refined = False

        if isinstance(outcome, NeedsMore) and self._has_refinement_budget():
            outcome, chunks = self._refine(
                query, plan, ui_filters, outcome, chunks, budget
            )
            refined = True

        answer_text = outcome.answer if isinstance(outcome, Answered) else ""
        sources = self._assemble_sources(chunks)
        return self._build_result(
            answer_text, sources, plan, budget, started, refined=refined
        )

    def retrieve(
        self,
        query: str,
        ui_filters: SearchFilters | None = None,
    ) -> SearchResult:
        """Plan and retrieve only — ranked sources, no synthesised answer.

        This is the "sources only" mode behind the MCP ``search_documents``
        tool: the calling agent synthesises its own answer, so the pipeline
        makes only the single planner LLM call and skips synthesis entirely.

        Args:
            query: The raw user search query.
            ui_filters: Explicit user-set filters; authoritative when set.

        Returns:
            A SearchResult whose ``answer`` is an empty string and whose
            ``sources`` are the ranked retrieved documents.
        """
        started = time.monotonic()
        budget = _LlmBudget()

        plan = self._plan(query, budget)
        chunks = self._retrieve_with_broaden(plan, ui_filters)
        sources = self._assemble_sources(chunks)
        return self._build_result(
            "", sources, plan, budget, started, refined=False
        )

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _plan(self, query: str, budget: _LlmBudget) -> QueryPlan:
        """Run the planner stage and record its single LLM call."""
        budget.record()
        return self._planner.plan(query)

    def _retrieve_with_broaden(
        self,
        plan: QueryPlan,
        ui_filters: SearchFilters | None,
    ) -> list[RetrievedChunk]:
        """Retrieve for *plan*; broaden and retry once if nothing is found.

        Resolves the plan's free-text filter candidates against the live
        taxonomy (UI filters bypass resolution), then runs hybrid retrieval.
        An empty result is retried once with the filters dropped (spec §6.3) —
        a mis-resolved or hallucinated filter is the most common cause of an
        otherwise-answerable query returning nothing.  Neither call is an LLM
        call.
        """
        facets = self._store_reader.list_facets()
        filters = resolve_filters(
            plan.filter_candidates, facets, ui_filters=ui_filters
        )
        chunks = self._retriever.retrieve(plan, filters)
        if chunks:
            return chunks

        # Empty retrieval — drop the filters and try once more.
        broadened_plan = broaden_plan(plan)
        broadened_filters = resolve_filters(
            broadened_plan.filter_candidates, facets, ui_filters=None
        )
        log.info("search.retrieval_broadened")
        return self._retriever.retrieve(broadened_plan, broadened_filters)

    def _synthesise(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        mode: str,
        budget: _LlmBudget,
    ) -> Answered | NeedsMore:
        """Run one synthesiser LLM call, recording it against the budget."""
        budget.record()
        return self._synthesizer.synthesise(query, chunks, mode=mode)

    def _refine(
        self,
        query: str,
        plan: QueryPlan,
        ui_filters: SearchFilters | None,
        needs_more: NeedsMore,
        previous_chunks: list[RetrievedChunk],
        budget: _LlmBudget,
    ) -> tuple[Answered | NeedsMore, list[RetrievedChunk]]:
        """Run the single bounded refinement pass (spec §6.3).

        Folds the synthesiser's adjustment hint into the plan, retrieves
        again, merges the new chunks with the previous round's, and runs the
        final-mode synthesise (which must answer or explicitly say "not
        found").  This is LLM call #3 — the last call the pipeline may make.

        Args:
            query: The raw user query.
            plan: The original query plan.
            ui_filters: The authoritative UI filters, if any.
            needs_more: The exploratory synthesiser's NeedsMore signal.
            previous_chunks: The chunks from the first retrieval round.
            budget: The LLM-call budget; the final synthesise is recorded here.

        Returns:
            A pair of the final synthesiser outcome and the merged chunk list
            used as its context (and as the result's source set).
        """
        log.info(
            "search.refined",
            query_prefix=query[:60],
            adjustment=needs_more.adjustment[:120],
        )
        adjusted_plan = adjust_plan(plan, needs_more.adjustment)
        new_chunks = self._retrieve_with_broaden(adjusted_plan, ui_filters)
        merged = _merge_chunks(previous_chunks, new_chunks)
        outcome = self._synthesise(query, merged, mode="final", budget=budget)
        return outcome, merged

    # ------------------------------------------------------------------
    # Source assembly and result construction
    # ------------------------------------------------------------------

    def _assemble_sources(
        self,
        chunks: list[RetrievedChunk],
    ) -> tuple[SourceDocument, ...]:
        """Build ranked SourceDocuments from the retrieved chunks.

        Groups chunks by document (keeping each document's best fused score
        and a snippet from its highest-scoring chunk), resolves correspondent
        and document-type names via one ``get_documents`` look-up, and builds
        a Paperless deep-link per document.  Documents are ordered by score,
        highest first.
        """
        if not chunks:
            return ()

        best_score, snippet = _best_chunk_per_document(chunks)
        document_ids = list(best_score.keys())
        indexed = self._store_reader.get_documents(document_ids)
        indexed_by_id = {document.id: document for document in indexed}

        sources = [
            self._build_source(
                document_id=document_id,
                score=best_score[document_id],
                snippet=snippet[document_id],
                indexed=indexed_by_id.get(document_id),
            )
            for document_id in document_ids
        ]
        sources.sort(key=lambda source: source.score, reverse=True)
        return tuple(sources)

    def _build_source(
        self,
        *,
        document_id: int,
        score: float,
        snippet: str,
        indexed: IndexedDocument | None,
    ) -> SourceDocument:
        """Build one SourceDocument, tolerating an absent index row.

        A document can be missing from the index look-up if it was pruned
        between retrieval and assembly — a rare race.  The source is still
        returned (the chunk text is real); only the taxonomy-resolved fields
        fall back to None.
        """
        return SourceDocument(
            document_id=document_id,
            title=indexed.title if indexed is not None else None,
            correspondent=indexed.correspondent if indexed is not None else None,
            document_type=indexed.document_type if indexed is not None else None,
            created=indexed.created if indexed is not None else None,
            snippet=snippet,
            paperless_url=self._paperless_url(document_id),
            score=score,
        )

    def _paperless_url(self, document_id: int) -> str:
        """Return the Paperless-ngx web deep-link for *document_id*.

        ``PAPERLESS_URL`` is stored already stripped of any trailing slash
        (see ``Settings._load_api_settings``); the document detail route in
        the Paperless-ngx UI is ``/documents/{id}/``.
        """
        return f"{self._settings.PAPERLESS_URL}/documents/{document_id}/"

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
        return SearchResult(
            answer=answer, sources=sources, plan=plan, stats=stats
        )

    def _no_match_result(
        self,
        plan: QueryPlan,
        budget: _LlmBudget,
        started: float,
    ) -> SearchResult:
        """Build the no-hits SearchResult — no sources, no synthesis call."""
        return self._build_result(
            _NO_MATCHES_ANSWER, (), plan, budget, started, refined=False
        )

    def _has_refinement_budget(self) -> bool:
        """Return whether the configured refinement budget permits a refine."""
        return self._settings.SEARCH_MAX_REFINEMENTS > 0


# ---------------------------------------------------------------------------
# Module-level helpers (no SearchCore state)
# ---------------------------------------------------------------------------


def _merge_chunks(
    previous: list[RetrievedChunk],
    new: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Merge two retrieved-chunk lists, de-duplicating by chunk id.

    The refinement pass synthesises over the union of both retrieval rounds
    (spec §6.3).  A chunk surfaced by both rounds is kept once; the first
    occurrence (the higher-ranked one, since ``previous`` leads) is retained.
    The merged list is ordered by fused score, highest first.
    """
    merged_by_id: dict[int, RetrievedChunk] = {}
    for chunk in [*previous, *new]:
        if chunk.chunk_id not in merged_by_id:
            merged_by_id[chunk.chunk_id] = chunk
    merged = list(merged_by_id.values())
    merged.sort(key=lambda chunk: chunk.rrf_score, reverse=True)
    return merged


def _best_chunk_per_document(
    chunks: list[RetrievedChunk],
) -> tuple[dict[int, float], dict[int, str]]:
    """Reduce chunks to each document's best score and a display snippet.

    A document may contribute several chunks; its source score is the highest
    fused score among them and its snippet is drawn from that best chunk.
    Iteration order does not matter — only a strict score comparison decides
    the winner, so the reduction is deterministic.

    Returns:
        A pair of ``{document_id: best_score}`` and ``{document_id: snippet}``.
    """
    best_score: dict[int, float] = {}
    snippet: dict[int, str] = {}
    for chunk in chunks:
        current = best_score.get(chunk.document_id)
        if current is None or chunk.rrf_score > current:
            best_score[chunk.document_id] = chunk.rrf_score
            snippet[chunk.document_id] = _snippet(chunk.text)
    return best_score, snippet


def _snippet(text: str) -> str:
    """Return a UI-display snippet — the chunk text trimmed to a preview.

    Collapses internal whitespace runs (OCR text is often ragged) and caps the
    length at ``_SNIPPET_MAX_CHARS`` with an ellipsis when truncated.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_MAX_CHARS:
        return collapsed
    return collapsed[:_SNIPPET_MAX_CHARS].rstrip() + "…"


def _elapsed_ms(started: float) -> int:
    """Return whole milliseconds elapsed since the monotonic timestamp *started*."""
    return int((time.monotonic() - started) * 1000)
