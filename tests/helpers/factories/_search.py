"""Search-pipeline test factories.

The ``tests.helpers.factories`` package re-exports every factory from its
``__init__``; this submodule holds the builders for the search-pipeline shapes
— :class:`~search.models.FilterCandidates`, :class:`~search.models.QueryPlan`,
:class:`~search.models.RetrievedChunk`, :class:`~search.models.SourceDocument`,
:class:`~search.models.SearchStats`, :class:`~search.models.SearchResult`,
:class:`~search.models.Answered`, :class:`~search.models.NeedsMore` — and the
store read-shapes the search tests need (:class:`~store.models.ChunkHit`,
:class:`~store.models.IndexedDocument`, :class:`~store.models.TaxonomyEntry`,
:class:`~store.models.FacetSet`, :class:`~store.models.IndexStats`).

Each factory fills every irrelevant field with a deterministic default so a
test spells out only the field under test (CODE_GUIDELINES §11.5).  These
replace the ~28 hand-rolled ``_make_*`` builders the search test files used to
each redeclare.
"""

from __future__ import annotations

from typing import Any

from search.models import (
    Answered,
    FilterCandidates,
    NeedsMore,
    QueryPlan,
    RetrievedChunk,
    SearchResult,
    SearchStats,
    SourceDocument,
)
from store.models import (
    ChunkHit,
    FacetSet,
    IndexedDocument,
    IndexStats,
    TaxonomyEntry,
)


# ---------------------------------------------------------------------------
# Planner / retriever shapes
# ---------------------------------------------------------------------------


def make_filter_candidates(
    *,
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
    date_from: str | None = None,
    date_to: str | None = None,
) -> FilterCandidates:
    """Create a FilterCandidates; every field defaults to "no candidate".

    The all-default call models the planner emitting no filter guesses; a test
    that exercises one candidate passes only that keyword.
    """
    return FilterCandidates(
        correspondent=correspondent,
        document_type=document_type,
        tags=tags,
        date_from=date_from,
        date_to=date_to,
    )


def make_query_plan(
    *,
    semantic_queries: tuple[str, ...] = ("test query",),
    keyword_terms: tuple[str, ...] = (),
    filter_candidates: FilterCandidates | None = None,
    sub_questions: tuple[str, ...] = (),
) -> QueryPlan:
    """Create a QueryPlan with a single semantic query and no filters.

    *filter_candidates* defaults to an all-``None`` :class:`FilterCandidates`
    (via :func:`make_filter_candidates`) so a planner test that does not care
    about filters need not spell one out.
    """
    return QueryPlan(
        semantic_queries=semantic_queries,
        keyword_terms=keyword_terms,
        filter_candidates=(
            filter_candidates
            if filter_candidates is not None
            else make_filter_candidates()
        ),
        sub_questions=sub_questions,
    )


def make_retrieved_chunk(
    *,
    chunk_id: int = 1,
    document_id: int = 1,
    text: str = "Retrieved chunk text.",
    page_hint: int | None = 1,
    rrf_score: float = 0.5,
) -> RetrievedChunk:
    """Create a RetrievedChunk — one fused chunk as the retriever returns it."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        page_hint=page_hint,
        rrf_score=rrf_score,
    )


# ---------------------------------------------------------------------------
# Synthesiser outcome shapes
# ---------------------------------------------------------------------------


def make_answered(
    *,
    answer: str = "The synthesised answer.",
    citations: tuple[int, ...] = (1,),
) -> Answered:
    """Create an Answered synthesiser outcome with one citation by default."""
    return Answered(answer=answer, citations=citations)


def make_needs_more(
    *, adjustment: str = "Broaden the search to related documents."
) -> NeedsMore:
    """Create a NeedsMore synthesiser outcome with a generic adjustment hint."""
    return NeedsMore(adjustment=adjustment)


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


def make_source_document(
    *,
    document_id: int = 1,
    title: str | None = "Test Document",
    correspondent: str | None = None,
    document_type: str | None = None,
    created: str | None = "2024-01-15T00:00:00Z",
    snippet: str = "A representative snippet.",
    paperless_url: str | None = None,
    score: float = 0.9,
) -> SourceDocument:
    """Create a SourceDocument — one ranked source in a SearchResult.

    *paperless_url* defaults to a deep-link derived from *document_id* so a
    test that does not care about the URL need not spell one out.
    """
    return SourceDocument(
        document_id=document_id,
        title=title,
        correspondent=correspondent,
        document_type=document_type,
        created=created,
        snippet=snippet,
        paperless_url=(
            paperless_url
            if paperless_url is not None
            else f"http://paperless.example:8000/documents/{document_id}/"
        ),
        score=score,
    )


def make_search_stats(
    *,
    llm_calls: int = 2,
    latency_ms: int = 100,
    refined: bool = False,
) -> SearchStats:
    """Create a SearchStats — the default models a normal two-call query."""
    return SearchStats(
        llm_calls=llm_calls, latency_ms=latency_ms, refined=refined
    )


def make_search_result(
    *,
    answer: str = "The synthesised answer.",
    sources: tuple[SourceDocument, ...] | None = None,
    plan: QueryPlan | None = None,
    stats: SearchStats | None = None,
) -> SearchResult:
    """Create a SearchResult with one source, a default plan, and default stats.

    Each absent argument is filled from the matching factory, so a test asserts
    on only the field it cares about.
    """
    return SearchResult(
        answer=answer,
        sources=(
            sources
            if sources is not None
            else (make_source_document(),)
        ),
        plan=plan if plan is not None else make_query_plan(),
        stats=stats if stats is not None else make_search_stats(),
    )


# ---------------------------------------------------------------------------
# Store read-shapes the search tests consume
# ---------------------------------------------------------------------------


def make_chunk_hit(
    *,
    chunk_id: int = 1,
    document_id: int = 1,
    text: str = "Chunk hit text.",
    page_hint: int | None = 1,
    score: float = 0.5,
) -> ChunkHit:
    """Create a ChunkHit — one ranked hit as a StoreReader search returns it."""
    return ChunkHit(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        page_hint=page_hint,
        score=score,
    )


def make_taxonomy_entry(
    *,
    kind: str = "correspondent",
    entry_id: int = 1,
    name: str = "ACME Corp",
) -> TaxonomyEntry:
    """Create a TaxonomyEntry — one row of the store's taxonomy table."""
    return TaxonomyEntry(kind=kind, id=entry_id, name=name)


def make_indexed_document(
    *,
    document_id: int = 1,
    title: str | None = "A Document",
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
    created: str | None = "2024-01-15T00:00:00+00:00",
) -> IndexedDocument:
    """Create an IndexedDocument as StoreReader.get_documents returns it."""
    return IndexedDocument(
        id=document_id,
        title=title,
        correspondent=correspondent,
        document_type=document_type,
        tags=tags,
        created=created,
    )


def make_facet_set(
    *,
    correspondents: tuple[TaxonomyEntry, ...] = (),
    document_types: tuple[TaxonomyEntry, ...] = (),
    tags: tuple[TaxonomyEntry, ...] = (),
    earliest: str | None = None,
    latest: str | None = None,
) -> FacetSet:
    """Create a FacetSet; every facet group defaults to empty."""
    return FacetSet(
        correspondents=correspondents,
        document_types=document_types,
        tags=tags,
        earliest=earliest,
        latest=latest,
    )


def make_index_stats(
    *,
    document_count: int = 0,
    chunk_count: int = 0,
    last_reconcile_at: str | None = "2024-06-01T12:00:00Z",
    embedding_model: str | None = "text-embedding-3-small",
) -> IndexStats:
    """Create an IndexStats; defaults model a reconciled, empty index.

    ``last_reconcile_at`` defaults to a real timestamp so the common healthz
    "index is ready" path needs no override; pass ``None`` for the
    never-reconciled case.
    """
    return IndexStats(
        document_count=document_count,
        chunk_count=chunk_count,
        last_reconcile_at=last_reconcile_at,
        embedding_model=embedding_model,
    )


# ---------------------------------------------------------------------------
# Settings-like mock for the search pipeline
# ---------------------------------------------------------------------------


def make_search_settings(**overrides: Any) -> Any:
    """Create a Settings-like MagicMock with every search-pipeline field set.

    The defaults span the planner, retriever, synthesiser, core, and the
    search/MCP servers, so this single factory replaces the per-file
    ``_make_settings`` mocks the search test files used to hand-roll.  The
    ``MAX_RETRIES`` / ``MAX_RETRY_BACKOFF_SECONDS`` ints keep the inherited
    ``@retry`` decorator on the planner and synthesiser well-formed even though
    tests patch ``_create_completion`` and never enter the retry loop.

    Args:
        **overrides: Any field override — e.g. ``SEARCH_MAX_REFINEMENTS=0``.
    """
    from unittest.mock import MagicMock

    defaults: dict[str, Any] = {
        "PAPERLESS_URL": "http://paperless.example:8000",
        "INDEX_DB_PATH": "/tmp/test-index.db",
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "EMBEDDING_DIMENSIONS": 4,
        "SEARCH_TOP_K": 10,
        "SEARCH_MAX_REFINEMENTS": 1,
        "SEARCH_MAX_CONCURRENT": 4,
        "SEARCH_PLANNER_MODEL": "gpt-5.4-mini",
        "SEARCH_ANSWER_MODEL": "gpt-5.4",
        "AI_MODELS": ["gpt-5.4-mini", "gpt-5.4"],
        "SEARCH_API_KEY": "test-search-api-key",
        "SEARCH_SESSION_TTL": 3600,
        "MAX_RETRIES": 3,
        "MAX_RETRY_BACKOFF_SECONDS": 30,
    }
    defaults.update(overrides)
    settings = MagicMock()
    for key, value in defaults.items():
        setattr(settings, key, value)
    return settings
