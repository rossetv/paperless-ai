"""Tests for search.retriever — hybrid retriever with RRF fusion.

Verifies:
- RRF fusion of two ranked lists produces hand-computed expected scores.
- A chunk appearing in multiple lists ranks above one appearing in only one.
- resolve_filters resolves an exact taxonomy name match.
- resolve_filters resolves a near-match after punctuation/case normalisation.
- resolve_filters drops an unresolvable candidate (never guesses).
- UI filters (ui_filters) override planner candidates entirely.
- retrieve() returns the top-K documents' chunks ordered by fused score.
- retrieve() returns [] when all ranked lists are empty.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import openai
import pytest

from common.embeddings import EmbeddingError
from search.models import FilterCandidates, QueryPlan, RetrievedChunk
from search.retriever import _RRF_K, Retriever, resolve_filters
from store.models import ChunkHit, FacetSet, TaxonomyEntry
from store.reader import SearchFilters


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(top_k: int = 5) -> MagicMock:
    """Build a minimal Settings-like mock for Retriever."""
    mock = MagicMock()
    mock.SEARCH_TOP_K = top_k
    return mock


def _make_query_plan(
    semantic_queries: tuple[str, ...] = ("query",),
    keyword_terms: tuple[str, ...] = (),
    sub_questions: tuple[str, ...] = (),
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
    date_from: str | None = None,
    date_to: str | None = None,
) -> QueryPlan:
    return QueryPlan(
        semantic_queries=semantic_queries,
        keyword_terms=keyword_terms,
        filter_candidates=FilterCandidates(
            correspondent=correspondent,
            document_type=document_type,
            tags=tags,
            date_from=date_from,
            date_to=date_to,
        ),
        sub_questions=sub_questions,
    )


def _make_chunk_hit(
    chunk_id: int,
    document_id: int,
    text: str = "chunk text",
    page_hint: int | None = None,
    score: float = 0.5,
) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        page_hint=page_hint,
        score=score,
    )


def _make_taxonomy_entry(kind: str, entry_id: int, name: str) -> TaxonomyEntry:
    return TaxonomyEntry(kind=kind, id=entry_id, name=name)


def _make_facet_set(
    correspondents: tuple[TaxonomyEntry, ...] = (),
    document_types: tuple[TaxonomyEntry, ...] = (),
    tags: tuple[TaxonomyEntry, ...] = (),
) -> FacetSet:
    return FacetSet(
        correspondents=correspondents,
        document_types=document_types,
        tags=tags,
        earliest=None,
        latest=None,
    )


def _no_filters() -> SearchFilters:
    return SearchFilters(
        date_from=None,
        date_to=None,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(),
    )


# ---------------------------------------------------------------------------
# RRF constant
# ---------------------------------------------------------------------------


def test_rrf_k_constant_is_sixty() -> None:
    """_RRF_K must be the canonical 60 from spec §6.2."""
    assert _RRF_K == 60


# ---------------------------------------------------------------------------
# RRF fusion — hand-computed expected scores
# ---------------------------------------------------------------------------


def test_rrf_fusion_hand_computed_two_lists() -> None:
    """RRF fuses two ranked lists; assert exact fused scores.

    List A (vector): chunk_id=1 at rank 0, chunk_id=2 at rank 1.
    List B (keyword): chunk_id=2 at rank 0, chunk_id=3 at rank 1.

    Expected RRF scores (1-based rank convention — rank 1 = position 0):
      chunk 1: 1/(60+1) = 1/61
      chunk 2: 1/(60+1) + 1/(60+1) = 1/61 + 1/61 = 2/61   <- appears in both
      chunk 3: 1/(60+2) = 1/62

    The retriever uses 1-based ranks: position 0 in the list → rank 1.
    """
    settings = _make_settings(top_k=10)

    store_reader = MagicMock()
    embedding_client = MagicMock()

    # Vector search returns [chunk1, chunk2]
    store_reader.vector_search.return_value = [
        _make_chunk_hit(chunk_id=1, document_id=10),
        _make_chunk_hit(chunk_id=2, document_id=20),
    ]
    # Keyword search returns [chunk2, chunk3]
    store_reader.keyword_search.return_value = [
        _make_chunk_hit(chunk_id=2, document_id=20),
        _make_chunk_hit(chunk_id=3, document_id=30),
    ]
    embedding_client.embed.return_value = [[0.1, 0.2, 0.3]]

    retriever = Retriever(settings, store_reader, embedding_client)
    plan = _make_query_plan(
        semantic_queries=("find me something",),
        keyword_terms=("term",),
    )
    chunks = retriever.retrieve(plan, _no_filters())

    # Build a map of chunk_id -> rrf_score from the results.
    score_by_chunk: dict[int, float] = {c.chunk_id: c.rrf_score for c in chunks}

    # Hand-computed expected scores (1-based rank: position 0 → rank 1):
    #   chunk 1: in list A at position 0 → rank 1  → 1/(60+1) = 1/61
    #   chunk 2: in list A at position 1 → rank 2  → 1/(60+2) = 1/62
    #            in list B at position 0 → rank 1  → 1/(60+1) = 1/61
    #            fused                              = 1/62 + 1/61
    #   chunk 3: in list B at position 1 → rank 2  → 1/(60+2) = 1/62
    expected_chunk1 = 1 / (60 + 1)
    expected_chunk2 = 1 / (60 + 2) + 1 / (60 + 1)
    expected_chunk3 = 1 / (60 + 2)

    assert score_by_chunk[2] == pytest.approx(expected_chunk2)
    assert score_by_chunk[1] == pytest.approx(expected_chunk1)
    assert score_by_chunk[3] == pytest.approx(expected_chunk3)


def test_chunk_in_multiple_lists_ranks_above_single_list() -> None:
    """A chunk appearing in two ranked lists must have a higher fused score."""
    settings = _make_settings(top_k=10)

    store_reader = MagicMock()
    embedding_client = MagicMock()

    store_reader.vector_search.return_value = [
        _make_chunk_hit(chunk_id=1, document_id=1),
        _make_chunk_hit(chunk_id=2, document_id=2),
    ]
    store_reader.keyword_search.return_value = [
        _make_chunk_hit(chunk_id=2, document_id=2),
    ]
    embedding_client.embed.return_value = [[0.1, 0.2]]

    retriever = Retriever(settings, store_reader, embedding_client)
    plan = _make_query_plan(
        semantic_queries=("query",),
        keyword_terms=("term",),
    )
    chunks = retriever.retrieve(plan, _no_filters())

    score_by_chunk: dict[int, float] = {c.chunk_id: c.rrf_score for c in chunks}

    # chunk 2 is in both lists; chunk 1 is only in the vector list.
    assert score_by_chunk[2] > score_by_chunk[1]


# ---------------------------------------------------------------------------
# resolve_filters — exact match
# ---------------------------------------------------------------------------


def test_resolve_filters_exact_correspondent_match() -> None:
    """resolve_filters resolves a correspondent candidate by exact name."""
    candidates = FilterCandidates(
        correspondent="ACME Corp",
        document_type=None,
        tags=(),
        date_from=None,
        date_to=None,
    )
    facets = _make_facet_set(
        correspondents=(
            _make_taxonomy_entry("correspondent", 7, "ACME Corp"),
        ),
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.correspondent_id == 7


def test_resolve_filters_exact_document_type_match() -> None:
    """resolve_filters resolves a document_type candidate by exact name."""
    candidates = FilterCandidates(
        correspondent=None,
        document_type="Invoice",
        tags=(),
        date_from=None,
        date_to=None,
    )
    facets = _make_facet_set(
        document_types=(
            _make_taxonomy_entry("document_type", 3, "Invoice"),
        ),
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.document_type_id == 3


def test_resolve_filters_exact_tag_match() -> None:
    """resolve_filters resolves a tag candidate by exact name."""
    candidates = FilterCandidates(
        correspondent=None,
        document_type=None,
        tags=("important",),
        date_from=None,
        date_to=None,
    )
    facets = _make_facet_set(
        tags=(
            _make_taxonomy_entry("tag", 5, "important"),
        ),
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.tag_ids == (5,)


# ---------------------------------------------------------------------------
# resolve_filters — normalised near-match
# ---------------------------------------------------------------------------


def test_resolve_filters_normalised_case_match() -> None:
    """resolve_filters resolves a candidate after case normalisation."""
    candidates = FilterCandidates(
        correspondent="acme corp",
        document_type=None,
        tags=(),
        date_from=None,
        date_to=None,
    )
    facets = _make_facet_set(
        correspondents=(
            _make_taxonomy_entry("correspondent", 7, "ACME Corp"),
        ),
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.correspondent_id == 7


def test_resolve_filters_normalised_punctuation_match() -> None:
    """resolve_filters resolves a candidate after stripping punctuation."""
    candidates = FilterCandidates(
        correspondent="npower",
        document_type=None,
        tags=(),
        date_from=None,
        date_to=None,
    )
    facets = _make_facet_set(
        correspondents=(
            # The taxonomy has "npower." with a trailing period.
            _make_taxonomy_entry("correspondent", 12, "npower."),
        ),
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.correspondent_id == 12


def test_resolve_filters_normalised_case_and_punctuation_match() -> None:
    """resolve_filters resolves after both case folding and punctuation removal."""
    candidates = FilterCandidates(
        correspondent=None,
        document_type="gas bill",
        tags=(),
        date_from=None,
        date_to=None,
    )
    facets = _make_facet_set(
        document_types=(
            _make_taxonomy_entry("document_type", 9, "Gas-Bill"),
        ),
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.document_type_id == 9


# ---------------------------------------------------------------------------
# resolve_filters — unresolvable candidate is dropped
# ---------------------------------------------------------------------------


def test_resolve_filters_drops_unresolvable_candidate() -> None:
    """resolve_filters drops a correspondent that matches nothing in the taxonomy."""
    candidates = FilterCandidates(
        correspondent="NonExistentCorp",
        document_type=None,
        tags=(),
        date_from=None,
        date_to=None,
    )
    facets = _make_facet_set(
        correspondents=(
            _make_taxonomy_entry("correspondent", 1, "Some Other Corp"),
        ),
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    # Must be None — not guessed to a wrong id.
    assert filters.correspondent_id is None


def test_resolve_filters_drops_unresolvable_tag() -> None:
    """resolve_filters drops a tag that matches nothing; resolves the ones that do."""
    candidates = FilterCandidates(
        correspondent=None,
        document_type=None,
        tags=("real-tag", "ghost-tag"),
        date_from=None,
        date_to=None,
    )
    facets = _make_facet_set(
        tags=(
            _make_taxonomy_entry("tag", 4, "real-tag"),
        ),
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    # Only the resolvable tag survives.
    assert filters.tag_ids == (4,)


# ---------------------------------------------------------------------------
# resolve_filters — date candidates pass through unchanged
# ---------------------------------------------------------------------------


def test_resolve_filters_date_candidates_pass_through() -> None:
    """resolve_filters passes date_from/date_to straight through."""
    candidates = FilterCandidates(
        correspondent=None,
        document_type=None,
        tags=(),
        date_from="2024-01-01",
        date_to="2024-12-31",
    )
    facets = _make_facet_set()

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.date_from == "2024-01-01"
    assert filters.date_to == "2024-12-31"


# ---------------------------------------------------------------------------
# resolve_filters — UI filters override planner candidates
# ---------------------------------------------------------------------------


def test_resolve_filters_ui_filters_override_planner_candidates() -> None:
    """When ui_filters is provided it bypasses free-text resolution entirely."""
    # The planner emitted a correspondent guess that would otherwise resolve.
    candidates = FilterCandidates(
        correspondent="ACME Corp",
        document_type=None,
        tags=(),
        date_from="2023-01-01",
        date_to=None,
    )
    facets = _make_facet_set(
        correspondents=(
            _make_taxonomy_entry("correspondent", 7, "ACME Corp"),
        ),
    )
    # The user explicitly set a different correspondent in the UI.
    ui_filters = SearchFilters(
        date_from="2022-01-01",
        date_to="2022-12-31",
        correspondent_id=99,
        document_type_id=None,
        tag_ids=(),
    )

    filters = resolve_filters(candidates, facets, ui_filters=ui_filters)

    # The UI filter is returned as-is; the planner's correspondent guess is ignored.
    assert filters is ui_filters
    assert filters.correspondent_id == 99
    assert filters.date_from == "2022-01-01"


def test_resolve_filters_ui_filters_none_falls_back_to_resolution() -> None:
    """When ui_filters is None, planner candidates are resolved normally."""
    candidates = FilterCandidates(
        correspondent="ACME Corp",
        document_type=None,
        tags=(),
        date_from=None,
        date_to=None,
    )
    facets = _make_facet_set(
        correspondents=(
            _make_taxonomy_entry("correspondent", 7, "ACME Corp"),
        ),
    )

    filters = resolve_filters(candidates, facets, ui_filters=None)

    assert filters.correspondent_id == 7


# ---------------------------------------------------------------------------
# retrieve — top-K document selection
# ---------------------------------------------------------------------------


def test_retrieve_returns_top_k_documents_chunks() -> None:
    """retrieve returns only chunks belonging to the top-K scoring documents."""
    settings = _make_settings(top_k=2)

    store_reader = MagicMock()
    embedding_client = MagicMock()

    # Three documents, each with one chunk, returned in vector search.
    # doc 10 is at rank 0 (best), doc 20 at rank 1, doc 30 at rank 2.
    store_reader.vector_search.return_value = [
        _make_chunk_hit(chunk_id=1, document_id=10),
        _make_chunk_hit(chunk_id=2, document_id=20),
        _make_chunk_hit(chunk_id=3, document_id=30),
    ]
    store_reader.keyword_search.return_value = []
    embedding_client.embed.return_value = [[0.1, 0.2]]

    retriever = Retriever(settings, store_reader, embedding_client)
    plan = _make_query_plan(semantic_queries=("query",))
    chunks = retriever.retrieve(plan, _no_filters())

    # Only 2 documents (top_k=2); doc 30 must not appear.
    document_ids = {c.document_id for c in chunks}
    assert 30 not in document_ids
    assert 10 in document_ids
    assert 20 in document_ids


def test_retrieve_results_ordered_by_fused_score_descending() -> None:
    """retrieve returns chunks ordered by RRF score, highest first."""
    settings = _make_settings(top_k=10)

    store_reader = MagicMock()
    embedding_client = MagicMock()

    # chunk 1 (doc 10) at rank 0 in vector; chunk 2 (doc 20) at rank 0 in keyword.
    # chunk 1 is also at rank 1 in keyword, so its fused score is higher.
    store_reader.vector_search.return_value = [
        _make_chunk_hit(chunk_id=1, document_id=10),
    ]
    store_reader.keyword_search.return_value = [
        _make_chunk_hit(chunk_id=2, document_id=20),
        _make_chunk_hit(chunk_id=1, document_id=10),
    ]
    embedding_client.embed.return_value = [[0.1]]

    retriever = Retriever(settings, store_reader, embedding_client)
    plan = _make_query_plan(
        semantic_queries=("query",),
        keyword_terms=("term",),
    )
    chunks = retriever.retrieve(plan, _no_filters())

    scores = [c.rrf_score for c in chunks]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# retrieve — empty retrieval
# ---------------------------------------------------------------------------


def test_retrieve_empty_when_all_ranked_lists_are_empty() -> None:
    """retrieve returns [] when no chunks are found by any search method."""
    settings = _make_settings(top_k=10)

    store_reader = MagicMock()
    embedding_client = MagicMock()

    store_reader.vector_search.return_value = []
    store_reader.keyword_search.return_value = []
    embedding_client.embed.return_value = [[0.0, 0.0]]

    retriever = Retriever(settings, store_reader, embedding_client)
    plan = _make_query_plan(
        semantic_queries=("obscure query",),
        keyword_terms=("unknown",),
    )
    chunks = retriever.retrieve(plan, _no_filters())

    assert chunks == []


# ---------------------------------------------------------------------------
# retrieve — sub-questions also trigger vector search
# ---------------------------------------------------------------------------


def test_retrieve_embeds_sub_questions_for_vector_search() -> None:
    """retrieve calls embed() for sub_questions, not only semantic_queries."""
    settings = _make_settings(top_k=10)

    store_reader = MagicMock()
    embedding_client = MagicMock()

    store_reader.vector_search.return_value = []
    store_reader.keyword_search.return_value = []
    # Two embeds: one for semantic_queries[0], one for sub_questions[0].
    embedding_client.embed.return_value = [[0.1], [0.2]]

    retriever = Retriever(settings, store_reader, embedding_client)
    plan = _make_query_plan(
        semantic_queries=("main query",),
        sub_questions=("sub question",),
    )
    retriever.retrieve(plan, _no_filters())

    # embed() must be called with both texts combined.
    embedding_client.embed.assert_called_once()
    texts_embedded = embedding_client.embed.call_args[0][0]
    assert "main query" in texts_embedded
    assert "sub question" in texts_embedded


# ---------------------------------------------------------------------------
# retrieve — embedding failures degrade to empty, never propagate (finding C3)
# ---------------------------------------------------------------------------


def _retryable_openai_error() -> openai.APIConnectionError:
    """A retryable OpenAI error — what embed() re-raises after exhausting retries."""
    return openai.APIConnectionError(request=MagicMock())


class TestRetrieveEmbeddingFailure:
    """An embedding failure makes the query contribute nothing — retrieve never raises.

    Finding C3: ``EmbeddingClient.embed`` raises ``EmbeddingError`` on a
    non-retryable failure (bad key, 400) and re-raises a retryable OpenAI
    error once its own retries are exhausted.  The retriever caught neither,
    so a bad key or an embedding-endpoint outage turned every search into an
    unhandled 500.  ``retrieve`` now degrades the affected query to empty.
    """

    def test_embedding_error_degrades_to_empty(self) -> None:
        """An EmbeddingError out of embed() yields [] — keyword-only plan, no hit."""
        settings = _make_settings(top_k=10)
        store_reader = MagicMock()
        embedding_client = MagicMock()
        embedding_client.embed.side_effect = EmbeddingError("bad API key")
        # No keyword terms, so with vector search dead there is nothing to fuse.
        store_reader.keyword_search.return_value = []

        retriever = Retriever(settings, store_reader, embedding_client)
        plan = _make_query_plan(semantic_queries=("a query",))

        # Must NOT raise.
        chunks = retriever.retrieve(plan, _no_filters())

        assert chunks == []
        # Vector search is never reached when embedding fails.
        store_reader.vector_search.assert_not_called()

    def test_retryable_openai_error_degrades_to_empty(self) -> None:
        """A retry-exhausted retryable OpenAI error out of embed() also degrades."""
        settings = _make_settings(top_k=10)
        store_reader = MagicMock()
        embedding_client = MagicMock()
        embedding_client.embed.side_effect = _retryable_openai_error()
        store_reader.keyword_search.return_value = []

        retriever = Retriever(settings, store_reader, embedding_client)
        plan = _make_query_plan(semantic_queries=("a query",))

        chunks = retriever.retrieve(plan, _no_filters())

        assert chunks == []

    def test_embedding_failure_still_allows_keyword_results(self) -> None:
        """When vector embedding fails, keyword search still contributes hits."""
        settings = _make_settings(top_k=10)
        store_reader = MagicMock()
        embedding_client = MagicMock()
        embedding_client.embed.side_effect = EmbeddingError("embedding endpoint down")
        # Keyword search still works and returns a hit.
        store_reader.keyword_search.return_value = [
            _make_chunk_hit(chunk_id=1, document_id=10),
        ]

        retriever = Retriever(settings, store_reader, embedding_client)
        plan = _make_query_plan(
            semantic_queries=("a query",),
            keyword_terms=("term",),
        )

        chunks = retriever.retrieve(plan, _no_filters())

        # The keyword hit survives even though vector embedding failed.
        assert {c.chunk_id for c in chunks} == {1}
