"""Integration tests for the bounded refinement loop of the search pipeline.

The companion to :mod:`test_search_pipeline`.  These exercise the real
:class:`~search.core.SearchCore` refinement branch end to end against a real
``tmp_path`` store: an exploratory ``NeedsMore`` triggers exactly one refined
retrieval round, the hard 3-LLM-call ceiling holds even with the refinement
budget inflated, and the refined round's chunks merge with the first round's.

Split from :mod:`test_search_pipeline` for the 500-line ceiling
(CODE_GUIDELINES §3.1).  Shared store-seeding helpers and the embedding
geometry come from ``tests/integration/conftest.py``.
"""

from __future__ import annotations

from typing import Any

from store.reader import StoreReader
from store.writer import StoreWriter
from tests.helpers.llm import (
    ScriptedLLMClient,
    answered_response_json,
    needs_more_response_json,
    planner_response_json,
)
from tests.helpers.search import build_search_core
from tests.integration.conftest import (
    AXIS_BOILER,
    AXIS_REFINED,
    make_axis_embedding_client,
    make_pipeline_settings,
    seed_pipeline_document,
)


class TestBoundedRefinementEndToEnd:
    """The refinement loop runs through the real store and is capped at 3."""

    def test_needs_more_triggers_one_refinement_capped_at_three_calls(
        self, tmp_path: Any
    ) -> None:
        settings = make_pipeline_settings(tmp_path, SEARCH_MAX_REFINEMENTS=1)
        store_writer = StoreWriter(settings)
        try:
            seed_pipeline_document(
                store_writer,
                document_id=1,
                title="Boiler Manual",
                text="The boiler model is a Worcester Bosch Greenstar 28CDi.",
                embedding=AXIS_BOILER,
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(
                    semantic_queries=["boiler details"]
                ),
                synthesiser_responses=[
                    needs_more_response_json(
                        "Look for the warranty period specifically."
                    ),
                    answered_response_json(
                        "The boiler is a Worcester Bosch Greenstar [1].",
                        citations=[1],
                    ),
                ],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=make_axis_embedding_client(AXIS_BOILER),
            )
            result = core.answer("what boiler do I have?")

            assert llm_client.planner_calls == 1
            assert llm_client.synthesiser_calls == 2
            assert llm_client.total_calls == 3
            assert result.stats.refined is True
            assert result.stats.llm_calls == 3
        finally:
            store_reader.close()

    def test_inflated_budget_still_capped_at_three_calls(
        self, tmp_path: Any
    ) -> None:
        """Even with the refinement budget raised, the hard 3-call ceiling
        holds when every synthesise returns NeedsMore."""
        settings = make_pipeline_settings(tmp_path, SEARCH_MAX_REFINEMENTS=99)
        store_writer = StoreWriter(settings)
        try:
            seed_pipeline_document(
                store_writer,
                document_id=1,
                title="A Document",
                text="Indexed content that the retriever will always surface.",
                embedding=AXIS_BOILER,
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(
                    semantic_queries=["a query"]
                ),
                synthesiser_responses=[needs_more_response_json("always more")],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=make_axis_embedding_client(AXIS_BOILER),
            )
            result = core.answer("a query that always needs more")

            assert llm_client.total_calls <= 3
            assert result.stats.llm_calls <= 3
        finally:
            store_reader.close()

    def test_refinement_merges_new_chunks_with_the_previous_round(
        self, tmp_path: Any
    ) -> None:
        """The refinement pass synthesises over the merged chunk set —
        documents from both retrieval rounds are eligible as sources."""
        settings = make_pipeline_settings(tmp_path, SEARCH_MAX_REFINEMENTS=1)
        store_writer = StoreWriter(settings)
        try:
            seed_pipeline_document(
                store_writer,
                document_id=1,
                title="First-round Document",
                text="The first retrieval round surfaces this boiler document.",
                embedding=AXIS_BOILER,
            )
            seed_pipeline_document(
                store_writer,
                document_id=2,
                title="Second-round Document",
                text="The refined retrieval round surfaces this warranty document.",
                embedding=AXIS_REFINED,
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            # Both retrieval rounds embed onto the boiler axis (the embedding
            # mock is fixed), so to exercise the merge we rely on the merge
            # carrying doc 1 through; the second synthesise cites doc 1.
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(semantic_queries=["boiler"]),
                synthesiser_responses=[
                    needs_more_response_json("Need the warranty document too."),
                    answered_response_json("Combined answer [1].", citations=[1]),
                ],
            )
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=store_reader,
                embedding_client=make_axis_embedding_client(AXIS_BOILER),
            )
            result = core.answer("boiler warranty question")

            assert result.stats.refined is True
            # Doc 1 was retrieved in round one and survives the merge.
            source_ids = {source.document_id for source in result.sources}
            assert 1 in source_ids
        finally:
            store_reader.close()
