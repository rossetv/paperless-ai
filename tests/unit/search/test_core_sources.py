"""Tests for search.core — retrieve(), source assembly, filters, degradation.

The companion to :mod:`test_core`, which covers the ``answer()`` bounded-loop
contract.  This file covers the rest of ``search.core``:

- ``retrieve()`` — the sources-only mode: only the planner LLM call, no
  synthesis, an empty answer string, ranked sources.
- SourceDocument assembly — resolved correspondent/type names, a correct
  Paperless deep-link, a snippet, None taxonomy fields for a bare document.
- ``ui_filters`` — bypass free-text resolution and reach the retriever.
- Embedding-failure degradation — an embedding-backend failure degrades to the
  no-match result instead of propagating a 500 (finding C3).

Split from :mod:`test_core` for the 500-line ceiling (CODE_GUIDELINES §3.1).
The core is assembled by ``build_search_core`` (see conftest.py).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from common.embeddings import EmbeddingError
from search.models import SearchResult, SourceDocument
from store.reader import SearchFilters
from tests.helpers.factories import make_chunk_hit, make_facet_set, make_search_settings
from tests.helpers.factories import make_indexed_document as _indexed
from tests.helpers.llm import (
    ScriptedLLMClient,
    answered_response_json,
    planner_response_json,
)
from tests.unit.search.conftest import build_search_core


def _embedding_client() -> MagicMock:
    """Build a mock EmbeddingClient returning one deterministic vector."""
    embedding_client = MagicMock()
    embedding_client.embed.return_value = [[0.1]]
    return embedding_client


def _store_reader(
    *,
    vector_hits: list | None = None,
    documents: list | None = None,
) -> MagicMock:
    """Build a mock StoreReader with canned vector hits and indexed documents."""
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.return_value = (
        vector_hits
        if vector_hits is not None
        else [make_chunk_hit(chunk_id=1, document_id=1)]
    )
    store_reader.keyword_search.return_value = []
    store_reader.get_documents.return_value = (
        documents if documents is not None else [_indexed()]
    )
    return store_reader


def _unreachable_synth_client() -> ScriptedLLMClient:
    """A scripted client whose synthesiser response must never be reached."""
    return ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[
            answered_response_json("must not happen", citations=[])
        ],
    )


# ---------------------------------------------------------------------------
# retrieve() — sources-only mode, only the planner call
# ---------------------------------------------------------------------------


class TestRetrieveOnly:
    """retrieve() plans and retrieves but never synthesises."""

    def test_retrieve_makes_only_the_planner_call(self) -> None:
        llm_client = _unreachable_synth_client()
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        core.retrieve("a sources-only query")

        assert llm_client.planner_calls == 1
        assert llm_client.synthesiser_calls == 0
        assert llm_client.total_calls == 1

    def test_retrieve_answer_field_is_empty(self) -> None:
        """retrieve() returns ranked sources but an empty answer string."""
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=_unreachable_synth_client(),
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        result = core.retrieve("a sources-only query")

        assert result.answer == ""

    def test_retrieve_returns_ranked_sources(self) -> None:
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=_unreachable_synth_client(),
            store_reader=_store_reader(
                vector_hits=[
                    make_chunk_hit(chunk_id=1, document_id=7),
                    make_chunk_hit(chunk_id=2, document_id=8),
                ],
                documents=[_indexed(document_id=7), _indexed(document_id=8)],
            ),
            embedding_client=_embedding_client(),
        )
        result = core.retrieve("a query")

        source_ids = {source.document_id for source in result.sources}
        assert source_ids == {7, 8}

    def test_retrieve_reports_one_llm_call_in_stats(self) -> None:
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=_unreachable_synth_client(),
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        result = core.retrieve("a query")

        assert result.stats.llm_calls == 1
        assert result.stats.refined is False

    def test_retrieve_on_empty_returns_no_sources(self) -> None:
        """retrieve() with nothing found returns an empty sources tuple."""
        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        store_reader.vector_search.return_value = []
        store_reader.keyword_search.return_value = []
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=_unreachable_synth_client(),
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        result = core.retrieve("nothing matches")

        assert result.sources == ()
        assert result.stats.llm_calls == 1


# ---------------------------------------------------------------------------
# SourceDocument assembly — resolved names and a correct paperless_url
# ---------------------------------------------------------------------------


class TestSourceDocumentAssembly:
    """SourceDocuments carry resolved taxonomy names and a Paperless deep-link."""

    def _answer_with_one_source(
        self, *, document_id: int, documents: list, chunk_text: str = "chunk text"
    ) -> SearchResult:
        """Run answer() against one seeded document and return the result."""
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json(
                    f"Answer [{document_id}].", citations=[document_id]
                )
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader(
                vector_hits=[
                    make_chunk_hit(
                        chunk_id=1, document_id=document_id, text=chunk_text
                    )
                ],
                documents=documents,
            ),
            embedding_client=_embedding_client(),
        )
        return core.answer("a query")

    def test_source_carries_resolved_correspondent_and_type(self) -> None:
        result = self._answer_with_one_source(
            document_id=3,
            documents=[
                _indexed(
                    document_id=3,
                    title="2024 Electricity Invoice",
                    correspondent="npower",
                    document_type="Invoice",
                )
            ],
        )

        source = result.sources[0]
        assert source.correspondent == "npower"
        assert source.document_type == "Invoice"
        assert source.title == "2024 Electricity Invoice"

    def test_source_paperless_url_joins_base_url_and_document_id(self) -> None:
        result = self._answer_with_one_source(
            document_id=42, documents=[_indexed(document_id=42)]
        )

        source = result.sources[0]
        # The base URL and the document id both appear in the deep-link.
        assert source.paperless_url.startswith("http://paperless.example:8000")
        assert "42" in source.paperless_url

    def test_source_snippet_is_drawn_from_a_retrieved_chunk(self) -> None:
        """Each source carries a non-empty snippet for UI display."""
        result = self._answer_with_one_source(
            document_id=5,
            documents=[_indexed(document_id=5)],
            chunk_text="The boiler warranty certificate is valid until 2028.",
        )

        source = result.sources[0]
        assert source.snippet != ""
        assert isinstance(source, SourceDocument)

    def test_source_with_no_taxonomy_has_none_names(self) -> None:
        """A document with no correspondent/type yields None on those fields."""
        result = self._answer_with_one_source(
            document_id=9,
            documents=[
                _indexed(document_id=9, correspondent=None, document_type=None)
            ],
        )

        source = result.sources[0]
        assert source.correspondent is None
        assert source.document_type is None


# ---------------------------------------------------------------------------
# UI filters are threaded through to retrieval
# ---------------------------------------------------------------------------


class TestUiFilters:
    """ui_filters bypass free-text resolution and reach the retriever."""

    def test_ui_filters_are_passed_to_vector_search(self) -> None:
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(correspondent="npower"),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        store_reader = _store_reader()
        ui_filters = SearchFilters(
            date_from=None,
            date_to=None,
            correspondent_id=55,
            document_type_id=None,
            tag_ids=(),
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        core.answer("a query", ui_filters=ui_filters)

        # With ui_filters set, free-text resolution is bypassed and the UI
        # filters reach vector_search unchanged.
        passed_filters = store_reader.vector_search.call_args[0][2]
        assert passed_filters is ui_filters


# ---------------------------------------------------------------------------
# Embedding failure — answer() degrades to the no-match result (finding C3)
# ---------------------------------------------------------------------------


class TestEmbeddingFailure:
    """An embedding-backend failure degrades to the no-match SearchResult.

    Finding C3: an ``EmbeddingError`` (bad/expired key, embedding-endpoint
    outage) raised inside retrieval used to propagate out of ``core.answer()``
    as an unhandled 500.  The retriever now catches it and degrades the query
    to empty; ``answer()`` then returns the ordinary "no matching documents"
    result with no synthesis call.
    """

    def _store_reader_no_keyword_hits(self) -> MagicMock:
        """A StoreReader whose keyword search finds nothing (vector path dead)."""
        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        store_reader.keyword_search.return_value = []
        return store_reader

    def test_answer_returns_no_match_result_on_embedding_error(self) -> None:
        """core.answer() returns a SearchResult, not an exception, when embed() fails."""
        embedding_client = MagicMock()
        embedding_client.embed.side_effect = EmbeddingError(
            "expired OPENAI_API_KEY"
        )
        llm_client = _unreachable_synth_client()
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=self._store_reader_no_keyword_hits(),
            embedding_client=embedding_client,
        )

        # Must NOT raise.
        result = core.answer("a query whose embedding cannot be produced")

        assert isinstance(result, SearchResult)
        # Retrieval degraded to empty → the no-match short-circuit fired:
        # only the planner ran, no synthesis call, no sources.
        assert result.sources == ()
        assert result.answer != ""
        assert llm_client.planner_calls == 1
        assert llm_client.synthesiser_calls == 0

    def test_retrieve_returns_no_sources_on_embedding_error(self) -> None:
        """core.retrieve() also degrades to empty sources on an embedding failure."""
        embedding_client = MagicMock()
        embedding_client.embed.side_effect = EmbeddingError(
            "embedding endpoint down"
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=_unreachable_synth_client(),
            store_reader=self._store_reader_no_keyword_hits(),
            embedding_client=embedding_client,
        )

        result = core.retrieve("a sources-only query")

        assert isinstance(result, SearchResult)
        assert result.sources == ()
        assert result.stats.llm_calls == 1
