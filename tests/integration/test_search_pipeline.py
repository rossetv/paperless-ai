"""Integration tests for the agentic search pipeline.

These exercise the real :class:`~search.core.SearchCore` over the real
planner, retriever, and synthesiser stages and a real
:class:`~store.reader.StoreReader` reading a ``tmp_path`` SQLite store seeded
through the real :class:`~store.writer.StoreWriter`.

Only the LLM transport and the embedding client are mocked — every store
transaction, every SQL query, RRF fusion, and filter resolution run for real.

Coverage here: a full pipeline run answers a query citing a real seeded
document; an empty store short-circuits with no synthesis call; ``retrieve()``
returns real ranked sources without an answer.  The bounded refinement loop is
covered in :mod:`test_search_pipeline_refinement` (split for the 500-line
ceiling, CODE_GUIDELINES §3.1).

The pipeline is assembled by ``build_search_core`` (tests.helpers.search): the
planner and synthesiser are real with their ``_create_completion`` patched by a
scripted driver, never via constructor injection.
"""

from __future__ import annotations

from typing import Any

from store.models import TaxonomyEntry
from store.reader import StoreReader
from store.writer import StoreWriter
from tests.helpers.llm import (
    ScriptedLLMClient,
    _make_spec,
    answered_response_json,
    planner_response_json,
)
from tests.helpers.search import build_search_core
from tests.integration.conftest import (
    AXIS_BOILER as _AXIS_BOILER,
)
from tests.integration.conftest import (
    AXIS_OTHER as _AXIS_OTHER,
)
from tests.integration.conftest import (
    make_axis_embedding_client as _make_embedding_client,
)
from tests.integration.conftest import (
    make_pipeline_settings as _make_settings,
)
from tests.integration.conftest import (
    seed_pipeline_document as _seed_document,
)


# ---------------------------------------------------------------------------
# Full pipeline — a query is answered from a real seeded document
# ---------------------------------------------------------------------------


class TestFullPipelineAnswer:
    """The whole pipeline answers a query against a real store."""

    def test_query_is_answered_citing_a_real_document(self, tmp_path: Any) -> None:
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            _seed_document(
                store_writer,
                document_id=1,
                title="Worcester Bosch Boiler Warranty",
                text="The boiler warranty certificate is valid until March 2028.",
                embedding=_AXIS_BOILER,
            )
            _seed_document(
                store_writer,
                document_id=2,
                title="Council Tax Letter",
                text="Your council tax band is D for the 2024 financial year.",
                embedding=_AXIS_OTHER,
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(
                    specs=[_make_spec(semantic="boiler warranty expiry")]
                ),
                synthesiser_responses=[
                    answered_response_json(
                        "Your boiler warranty is valid until March 2028 [1].",
                        citations=[1],
                    )
                ],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=_make_embedding_client(_AXIS_BOILER),
            )
            result = core.answer("when does my boiler warranty expire?")

            assert llm_client.total_calls == 2
            assert "2028" in result.answer
            # The boiler document is the nearest on the boiler axis.
            assert result.sources[0].document_id == 1
            assert result.sources[0].title == "Worcester Bosch Boiler Warranty"
        finally:
            store_reader.close()

    def test_source_carries_resolved_taxonomy_names(self, tmp_path: Any) -> None:
        """SourceDocument correspondent/type names come from the real
        taxonomy table joined at query time."""
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            store_writer.refresh_taxonomy(
                [
                    TaxonomyEntry(kind="correspondent", id=10, name="npower"),
                    TaxonomyEntry(kind="document_type", id=20, name="Invoice"),
                ]
            )
            _seed_document(
                store_writer,
                document_id=1,
                title="2024 Electricity Invoice",
                text="Your electricity bill total is £142.50 for the quarter.",
                embedding=_AXIS_BOILER,
                correspondent_id=10,
                document_type_id=20,
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(
                    specs=[_make_spec(semantic="electricity bill total")]
                ),
                synthesiser_responses=[
                    answered_response_json("The total is £142.50 [1].", citations=[1])
                ],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=_make_embedding_client(_AXIS_BOILER),
            )
            result = core.answer("how much was my electricity bill?")

            source = result.sources[0]
            assert source.correspondent == "npower"
            assert source.document_type == "Invoice"
        finally:
            store_reader.close()

    def test_source_paperless_url_is_built_from_base_url(self, tmp_path: Any) -> None:
        settings = _make_settings(
            tmp_path, PAPERLESS_URL="http://paperless.example:8000"
        )
        store_writer = StoreWriter(settings)
        try:
            _seed_document(
                store_writer,
                document_id=77,
                title="A Document",
                text="Some indexed content about a topic worth retrieving.",
                embedding=_AXIS_BOILER,
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(
                    specs=[_make_spec(semantic="a topic")]
                ),
                synthesiser_responses=[
                    answered_response_json("Here is the answer [77].", citations=[77])
                ],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=_make_embedding_client(_AXIS_BOILER),
            )
            result = core.answer("tell me about the topic")

            url = result.sources[0].paperless_url
            assert url.startswith("http://paperless.example:8000")
            assert "77" in url
        finally:
            store_reader.close()


# ---------------------------------------------------------------------------
# Empty retrieval — short-circuit against a real (empty) store
# ---------------------------------------------------------------------------


class TestEmptyRetrievalEndToEnd:
    """A query against an empty store short-circuits before synthesis."""

    def test_empty_store_returns_no_matches_without_synthesis(
        self, tmp_path: Any
    ) -> None:
        settings = _make_settings(tmp_path)
        # Create the schema but seed nothing.
        StoreWriter(settings).close()

        store_reader = StoreReader(settings)
        try:
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(
                    specs=[_make_spec(semantic="anything")]
                ),
                synthesiser_responses=[
                    answered_response_json("must not be reached", citations=[])
                ],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=_make_embedding_client(_AXIS_BOILER),
            )
            result = core.answer("a query against an empty index")

            assert llm_client.planner_calls == 1
            assert llm_client.synthesiser_calls == 0
            assert result.stats.llm_calls == 1
            assert result.sources == ()
            assert result.answer != ""
        finally:
            store_reader.close()


# ---------------------------------------------------------------------------
# retrieve() — sources only, against a real store
# ---------------------------------------------------------------------------


class TestRetrieveOnlyEndToEnd:
    """retrieve() returns real ranked sources and never synthesises."""

    def test_retrieve_returns_sources_without_an_answer(self, tmp_path: Any) -> None:
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            _seed_document(
                store_writer,
                document_id=1,
                title="Indexed Document",
                text="Content that the sources-only retrieval will surface.",
                embedding=_AXIS_BOILER,
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(
                    specs=[_make_spec(semantic="indexed content")]
                ),
                synthesiser_responses=[
                    answered_response_json("must not be reached", citations=[])
                ],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=_make_embedding_client(_AXIS_BOILER),
            )
            result = core.retrieve("find indexed content")

            assert llm_client.planner_calls == 1
            assert llm_client.synthesiser_calls == 0
            assert result.answer == ""
            assert result.stats.llm_calls == 1
            assert len(result.sources) == 1
            assert result.sources[0].document_id == 1
        finally:
            store_reader.close()
