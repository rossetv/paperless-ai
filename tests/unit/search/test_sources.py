"""Tests for search.sources — pure chunk→SourceDocument assembly (spec §6.4).

The source-assembly logic was lifted out of core.py into this focused module;
core's existing tests still cover it through the public API, and these add
direct unit coverage of the pure functions (CODE_GUIDELINES §11.2).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from search.sources import _best_chunk_per_document, _snippet, assemble_sources
from tests.helpers.factories import (
    make_indexed_document,
    make_relevance_thresholds,
    make_retrieved_chunk,
)

_BASE_URL = "http://paperless.example:8000"
_THRESHOLDS = make_relevance_thresholds()


def _reader(*indexed) -> MagicMock:
    store_reader = MagicMock()
    store_reader.get_documents.return_value = list(indexed)
    return store_reader


def _assemble(chunks, reader):
    return assemble_sources(chunks, reader, _BASE_URL, _THRESHOLDS)


class TestAssembleSources:
    def test_empty_chunks_yields_no_sources(self) -> None:
        assert _assemble([], _reader()) == ()

    def test_groups_chunks_by_document_keeping_best_score(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=7, rrf_score=0.2),
            make_retrieved_chunk(chunk_id=2, document_id=7, rrf_score=0.9),
        ]
        sources = _assemble(chunks, _reader(make_indexed_document(document_id=7)))
        assert len(sources) == 1
        assert sources[0].document_id == 7
        assert sources[0].score == 0.9  # best of the two chunks

    def test_sources_are_ordered_by_score_descending(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=1, rrf_score=0.1),
            make_retrieved_chunk(chunk_id=2, document_id=2, rrf_score=0.8),
        ]
        reader = _reader(
            make_indexed_document(document_id=1),
            make_indexed_document(document_id=2),
        )
        sources = _assemble(chunks, reader)
        assert [s.document_id for s in sources] == [2, 1]

    def test_paperless_url_joins_base_and_document_id(self) -> None:
        chunks = [make_retrieved_chunk(chunk_id=1, document_id=42, rrf_score=0.5)]
        sources = _assemble(chunks, _reader(make_indexed_document(document_id=42)))
        assert sources[0].paperless_url == f"{_BASE_URL}/documents/42/"

    def test_resolves_taxonomy_names_from_the_index(self) -> None:
        chunks = [make_retrieved_chunk(chunk_id=1, document_id=5, rrf_score=0.5)]
        indexed = make_indexed_document(
            document_id=5, correspondent="npower", document_type="invoice"
        )
        sources = _assemble(chunks, _reader(indexed))
        assert sources[0].correspondent == "npower"
        assert sources[0].document_type == "invoice"

    def test_missing_index_row_falls_back_to_none_names(self) -> None:
        # Document retrieved but pruned before assembly: get_documents returns [].
        chunks = [make_retrieved_chunk(chunk_id=1, document_id=9, rrf_score=0.5)]
        sources = _assemble(chunks, _reader())
        assert len(sources) == 1
        assert sources[0].title is None
        assert sources[0].correspondent is None
        assert sources[0].paperless_url == f"{_BASE_URL}/documents/9/"


class TestRelevanceTier:
    """The qualitative tier is derived from a document's best vector similarity
    via the standalone cut-points: weak < 0.60 ≤ partial < 0.66 ≤ good < 0.70 ≤
    strong."""

    def _tier_for(self, similarity: float | None) -> str:
        chunks = [
            make_retrieved_chunk(
                chunk_id=1, document_id=1, rrf_score=0.5, vector_similarity=similarity
            )
        ]
        sources = _assemble(chunks, _reader(make_indexed_document(document_id=1)))
        return sources[0].relevance_tier

    def test_strong_at_or_above_floor_plus_010(self) -> None:
        assert self._tier_for(0.74) == "strong"  # e.g. the property-deeds query

    def test_good_band(self) -> None:
        assert self._tier_for(0.68) == "good"

    def test_partial_band(self) -> None:
        assert self._tier_for(0.62) == "partial"

    def test_weak_below_floor(self) -> None:
        assert self._tier_for(0.55) == "weak"  # off-topic / vague

    def test_keyword_only_document_defaults_to_good(self) -> None:
        # No vector similarity (keyword-only hit) → "good", not "weak".
        assert self._tier_for(None) == "good"

    def test_uses_the_best_similarity_across_a_documents_chunks(self) -> None:
        # The higher-similarity chunk decides the tier even when a lower-
        # similarity chunk wins the rrf_score (and thus the snippet).
        chunks = [
            make_retrieved_chunk(
                chunk_id=1, document_id=1, rrf_score=0.9, vector_similarity=0.55
            ),
            make_retrieved_chunk(
                chunk_id=2, document_id=1, rrf_score=0.1, vector_similarity=0.74
            ),
        ]
        sources = _assemble(chunks, _reader(make_indexed_document(document_id=1)))
        assert sources[0].relevance_tier == "strong"


class TestBestChunkPerDocument:
    def test_picks_the_highest_scoring_chunk_snippet(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=1, text="low", rrf_score=0.1),
            make_retrieved_chunk(chunk_id=2, document_id=1, text="high", rrf_score=0.9),
        ]
        best_score, snippet, best_similarity = _best_chunk_per_document(chunks)
        assert best_score == {1: 0.9}
        assert snippet == {1: "high"}
        assert 1 in best_similarity


class TestSnippet:
    def test_collapses_whitespace(self) -> None:
        assert _snippet("a   ragged\n\ntext") == "a ragged text"

    def test_truncates_with_ellipsis(self) -> None:
        long_text = "x " * 400
        snippet = _snippet(long_text)
        assert snippet.endswith("…")
        assert len(snippet) <= 281  # 280 chars + the ellipsis
