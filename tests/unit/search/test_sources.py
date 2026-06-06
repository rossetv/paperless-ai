"""Tests for search.sources — pure chunk→SourceDocument assembly (spec §6.4).

The source-assembly logic was lifted out of core.py into this focused module;
core's existing tests still cover it through the public API, and these add
direct unit coverage of the pure functions (CODE_GUIDELINES §11.2).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from search.sources import _best_chunk_per_document, _snippet, assemble_sources
from tests.helpers.factories import make_indexed_document, make_retrieved_chunk

_BASE_URL = "http://paperless.example:8000"


def _reader(*indexed) -> MagicMock:
    store_reader = MagicMock()
    store_reader.get_documents.return_value = list(indexed)
    return store_reader


class TestAssembleSources:
    def test_empty_chunks_yields_no_sources(self) -> None:
        assert assemble_sources([], _reader(), _BASE_URL) == ()

    def test_groups_chunks_by_document_keeping_best_score(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=7, rrf_score=0.2),
            make_retrieved_chunk(chunk_id=2, document_id=7, rrf_score=0.9),
        ]
        sources = assemble_sources(
            chunks, _reader(make_indexed_document(document_id=7)), _BASE_URL
        )
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
        sources = assemble_sources(chunks, reader, _BASE_URL)
        assert [s.document_id for s in sources] == [2, 1]

    def test_paperless_url_joins_base_and_document_id(self) -> None:
        chunks = [make_retrieved_chunk(chunk_id=1, document_id=42, rrf_score=0.5)]
        sources = assemble_sources(
            chunks, _reader(make_indexed_document(document_id=42)), _BASE_URL
        )
        assert sources[0].paperless_url == f"{_BASE_URL}/documents/42/"

    def test_resolves_taxonomy_names_from_the_index(self) -> None:
        chunks = [make_retrieved_chunk(chunk_id=1, document_id=5, rrf_score=0.5)]
        indexed = make_indexed_document(
            document_id=5, correspondent="npower", document_type="invoice"
        )
        sources = assemble_sources(chunks, _reader(indexed), _BASE_URL)
        assert sources[0].correspondent == "npower"
        assert sources[0].document_type == "invoice"

    def test_missing_index_row_falls_back_to_none_names(self) -> None:
        # Document retrieved but pruned before assembly: get_documents returns [].
        chunks = [make_retrieved_chunk(chunk_id=1, document_id=9, rrf_score=0.5)]
        sources = assemble_sources(chunks, _reader(), _BASE_URL)
        assert len(sources) == 1
        assert sources[0].title is None
        assert sources[0].correspondent is None
        assert sources[0].paperless_url == f"{_BASE_URL}/documents/9/"


class TestBestChunkPerDocument:
    def test_picks_the_highest_scoring_chunk_snippet(self) -> None:
        chunks = [
            make_retrieved_chunk(chunk_id=1, document_id=1, text="low", rrf_score=0.1),
            make_retrieved_chunk(chunk_id=2, document_id=1, text="high", rrf_score=0.9),
        ]
        best_score, snippet = _best_chunk_per_document(chunks)
        assert best_score == {1: 0.9}
        assert snippet == {1: "high"}


class TestSnippet:
    def test_collapses_whitespace(self) -> None:
        assert _snippet("a   ragged\n\ntext") == "a ragged text"

    def test_truncates_with_ellipsis(self) -> None:
        long_text = "x " * 400
        snippet = _snippet(long_text)
        assert snippet.endswith("…")
        assert len(snippet) <= 281  # 280 chars + the ellipsis
