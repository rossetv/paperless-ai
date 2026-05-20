"""Tests for search.retriever — RRF fusion and the retrieve() entry point.

Verifies:
- RRF fusion of two ranked lists produces hand-computed expected scores.
- A chunk appearing in multiple lists ranks above one appearing in only one.
- retrieve() returns the top-K documents' chunks ordered by fused score.
- retrieve() returns [] when all ranked lists are empty.
- retrieve() embeds sub-questions as well as semantic queries.
- An embedding failure degrades the query to empty — retrieve() never raises
  (finding C3).

``resolve_filters`` — the retriever's other public surface — is covered in
:mod:`test_retriever_filters` (split for the 500-line ceiling, §3.1).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import openai
import pytest

from common.embeddings import EmbeddingError
from search.retriever import _RRF_K, Retriever
from tests.helpers.factories import (
    make_chunk_hit,
    make_query_plan,
    make_search_filters,
    make_search_settings,
)


def _retriever(top_k: int = 5) -> tuple[Retriever, MagicMock, MagicMock]:
    """Build a Retriever over fresh mocks; return it with the store and client.

    The caller scripts ``store_reader.vector_search`` /
    ``store_reader.keyword_search`` and ``embedding_client.embed``.
    """
    store_reader = MagicMock()
    embedding_client = MagicMock()
    retriever = Retriever(
        make_search_settings(SEARCH_TOP_K=top_k), store_reader, embedding_client
    )
    return retriever, store_reader, embedding_client


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
      chunk 2: 1/(60+2) + 1/(60+1)   <- appears in both
      chunk 3: 1/(60+2) = 1/62
    """
    retriever, store_reader, embedding_client = _retriever(top_k=10)
    store_reader.vector_search.return_value = [
        make_chunk_hit(chunk_id=1, document_id=10),
        make_chunk_hit(chunk_id=2, document_id=20),
    ]
    store_reader.keyword_search.return_value = [
        make_chunk_hit(chunk_id=2, document_id=20),
        make_chunk_hit(chunk_id=3, document_id=30),
    ]
    embedding_client.embed.return_value = [[0.1, 0.2, 0.3]]

    plan = make_query_plan(
        semantic_queries=("find me something",), keyword_terms=("term",)
    )
    chunks = retriever.retrieve(plan, make_search_filters())

    score_by_chunk = {chunk.chunk_id: chunk.rrf_score for chunk in chunks}
    expected_chunk1 = 1 / (60 + 1)
    expected_chunk2 = 1 / (60 + 2) + 1 / (60 + 1)
    expected_chunk3 = 1 / (60 + 2)

    assert score_by_chunk[2] == pytest.approx(expected_chunk2)
    assert score_by_chunk[1] == pytest.approx(expected_chunk1)
    assert score_by_chunk[3] == pytest.approx(expected_chunk3)


def test_chunk_in_multiple_lists_ranks_above_single_list() -> None:
    """A chunk appearing in two ranked lists must have a higher fused score."""
    retriever, store_reader, embedding_client = _retriever(top_k=10)
    store_reader.vector_search.return_value = [
        make_chunk_hit(chunk_id=1, document_id=1),
        make_chunk_hit(chunk_id=2, document_id=2),
    ]
    store_reader.keyword_search.return_value = [
        make_chunk_hit(chunk_id=2, document_id=2),
    ]
    embedding_client.embed.return_value = [[0.1, 0.2]]

    plan = make_query_plan(
        semantic_queries=("query",), keyword_terms=("term",)
    )
    chunks = retriever.retrieve(plan, make_search_filters())

    score_by_chunk = {chunk.chunk_id: chunk.rrf_score for chunk in chunks}
    # chunk 2 is in both lists; chunk 1 is only in the vector list.
    assert score_by_chunk[2] > score_by_chunk[1]


# ---------------------------------------------------------------------------
# retrieve — top-K document selection
# ---------------------------------------------------------------------------


def test_retrieve_returns_top_k_documents_chunks() -> None:
    """retrieve returns only chunks belonging to the top-K scoring documents."""
    retriever, store_reader, embedding_client = _retriever(top_k=2)
    # Three documents, each with one chunk; doc 10 ranks best, doc 30 worst.
    store_reader.vector_search.return_value = [
        make_chunk_hit(chunk_id=1, document_id=10),
        make_chunk_hit(chunk_id=2, document_id=20),
        make_chunk_hit(chunk_id=3, document_id=30),
    ]
    store_reader.keyword_search.return_value = []
    embedding_client.embed.return_value = [[0.1, 0.2]]

    chunks = retriever.retrieve(
        make_query_plan(semantic_queries=("query",)), make_search_filters()
    )

    document_ids = {chunk.document_id for chunk in chunks}
    assert 30 not in document_ids
    assert 10 in document_ids
    assert 20 in document_ids


def test_retrieve_results_ordered_by_fused_score_descending() -> None:
    """retrieve returns chunks ordered by RRF score, highest first."""
    retriever, store_reader, embedding_client = _retriever(top_k=10)
    # chunk 1 is in both lists, so its fused score is higher than chunk 2's.
    store_reader.vector_search.return_value = [
        make_chunk_hit(chunk_id=1, document_id=10),
    ]
    store_reader.keyword_search.return_value = [
        make_chunk_hit(chunk_id=2, document_id=20),
        make_chunk_hit(chunk_id=1, document_id=10),
    ]
    embedding_client.embed.return_value = [[0.1]]

    plan = make_query_plan(
        semantic_queries=("query",), keyword_terms=("term",)
    )
    chunks = retriever.retrieve(plan, make_search_filters())

    scores = [chunk.rrf_score for chunk in chunks]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# retrieve — empty retrieval
# ---------------------------------------------------------------------------


def test_retrieve_empty_when_all_ranked_lists_are_empty() -> None:
    """retrieve returns [] when no chunks are found by any search method."""
    retriever, store_reader, embedding_client = _retriever(top_k=10)
    store_reader.vector_search.return_value = []
    store_reader.keyword_search.return_value = []
    embedding_client.embed.return_value = [[0.0, 0.0]]

    plan = make_query_plan(
        semantic_queries=("obscure query",), keyword_terms=("unknown",)
    )
    chunks = retriever.retrieve(plan, make_search_filters())

    assert chunks == []


# ---------------------------------------------------------------------------
# retrieve — sub-questions also trigger vector search
# ---------------------------------------------------------------------------


def test_retrieve_embeds_sub_questions_for_vector_search() -> None:
    """retrieve calls embed() for sub_questions, not only semantic_queries."""
    retriever, store_reader, embedding_client = _retriever(top_k=10)
    store_reader.vector_search.return_value = []
    store_reader.keyword_search.return_value = []
    embedding_client.embed.return_value = [[0.1], [0.2]]

    plan = make_query_plan(
        semantic_queries=("main query",), sub_questions=("sub question",)
    )
    retriever.retrieve(plan, make_search_filters())

    embedding_client.embed.assert_called_once()
    texts_embedded = embedding_client.embed.call_args[0][0]
    assert "main query" in texts_embedded
    assert "sub question" in texts_embedded


# ---------------------------------------------------------------------------
# retrieve — embedding failures degrade to empty, never propagate (finding C3)
# ---------------------------------------------------------------------------


def _retryable_openai_error() -> openai.APIConnectionError:
    """A retryable OpenAI error — what embed() re-raises after exhausting retries.

    The retriever catches ``EMBEDDING_FAILURE_EXCEPTIONS``, whose retryable
    half is ``openai.APIError``; constructing one here is fixture-building for
    a documented-catch contract, not a production openai call.
    """
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
        retriever, store_reader, embedding_client = _retriever(top_k=10)
        embedding_client.embed.side_effect = EmbeddingError("bad API key")
        # No keyword terms, so with vector search dead there is nothing to fuse.
        store_reader.keyword_search.return_value = []

        # Must NOT raise.
        chunks = retriever.retrieve(
            make_query_plan(semantic_queries=("a query",)),
            make_search_filters(),
        )

        assert chunks == []
        # Vector search is never reached when embedding fails.
        store_reader.vector_search.assert_not_called()

    def test_retryable_openai_error_degrades_to_empty(self) -> None:
        """A retry-exhausted retryable OpenAI error out of embed() also degrades."""
        retriever, store_reader, embedding_client = _retriever(top_k=10)
        embedding_client.embed.side_effect = _retryable_openai_error()
        store_reader.keyword_search.return_value = []

        chunks = retriever.retrieve(
            make_query_plan(semantic_queries=("a query",)),
            make_search_filters(),
        )

        assert chunks == []

    def test_embedding_failure_still_allows_keyword_results(self) -> None:
        """When vector embedding fails, keyword search still contributes hits."""
        retriever, store_reader, embedding_client = _retriever(top_k=10)
        embedding_client.embed.side_effect = EmbeddingError(
            "embedding endpoint down"
        )
        store_reader.keyword_search.return_value = [
            make_chunk_hit(chunk_id=1, document_id=10),
        ]

        plan = make_query_plan(
            semantic_queries=("a query",), keyword_terms=("term",)
        )
        chunks = retriever.retrieve(plan, make_search_filters())

        # The keyword hit survives even though vector embedding failed.
        assert {chunk.chunk_id for chunk in chunks} == {1}
