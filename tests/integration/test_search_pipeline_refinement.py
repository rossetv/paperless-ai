"""Integration tests for the bounded refinement loop of the search pipeline.

The companion to :mod:`test_search_pipeline`.  These exercise the real
:class:`~search.core.SearchCore` refinement branch end to end against a real
``tmp_path`` store: an exploratory ``NeedsMore`` triggers a refined retrieval
round, the loop runs exactly ``SEARCH_MAX_REFINEMENTS`` passes (bounded by the
``(2 + j) * (1 + SEARCH_MAX_REFINEMENTS)`` per-query budget, where ``j`` is 1
when ``SEARCH_GATE_JUDGE`` is on), and the refined round's chunks merge with
the first round's.

Split from :mod:`test_search_pipeline` for the 500-line ceiling
(CODE_GUIDELINES §3.1).  Shared store-seeding helpers and the embedding
geometry come from ``tests/integration/conftest.py``.
"""

from __future__ import annotations

from typing import Any

from store.models import SearchFilters
from store.reader import StoreReader
from store.writer import StoreWriter
from tests.helpers.llm import (
    ScriptedLLMClient,
    _make_spec,
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


class _VectorSearchSpy:
    """Wraps a StoreReader, recording every ``vector_search`` filters argument.

    Lets a test prove the refined retrieval used a DIFFERENT date-scoped filter
    than the first pass — the planner re-plan steers retrieval, not a blind
    broaden. Every other StoreReader method is delegated unchanged.
    """

    def __init__(self, reader: StoreReader) -> None:
        self._reader = reader
        self.vector_filters: list[SearchFilters] = []

    def vector_search(self, embedding: Any, k: int, filters: SearchFilters) -> Any:
        self.vector_filters.append(filters)
        return self._reader.vector_search(embedding, k, filters)

    def __getattr__(self, name: str) -> Any:
        # Delegate everything else (list_facets, get_documents, get_stats, …).
        return getattr(self._reader, name)


class TestBoundedRefinementEndToEnd:
    """The refinement loop runs through the real store, bounded by the per-query
    LLM-call ceiling (Phase 2: 2 + 2 * SEARCH_MAX_REFINEMENTS with the judge gate
    off)."""

    def test_one_refinement_makes_three_calls(self, tmp_path: Any) -> None:
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
                    specs=[_make_spec(semantic="boiler details")]
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

            # Phase 2: the refinement re-plans before re-synthesising. With no
            # scripted re-plan response the re-plan resolves to the same specs as
            # pass 1 (the no-op path): planner + exploratory synth + re-plan +
            # final synth = 4.
            assert llm_client.planner_calls == 1
            assert llm_client.replan_calls == 1
            assert llm_client.synthesiser_calls == 2
            assert llm_client.total_calls == 4
            assert result.stats.refined is True
            assert result.stats.llm_calls == 4
        finally:
            store_reader.close()

    def test_call_count_follows_max_refinements_end_to_end(self, tmp_path: Any) -> None:
        """End to end, the loop runs exactly SEARCH_MAX_REFINEMENTS passes when
        every synthesise returns NeedsMore. Phase 2: each pass costs a re-plan
        plus a synthesise, so the total is 2 + 2 * SEARCH_MAX_REFINEMENTS,
        bounded by the per-query budget."""
        settings = make_pipeline_settings(tmp_path, SEARCH_MAX_REFINEMENTS=4)
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
                    specs=[_make_spec(semantic="a query")]
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

            # Phase 2: each pass is a re-plan + a synthesise (the no-op path, no
            # scripted re-plan response). planner + exploratory + 4 * (re-plan +
            # synth) = 2 + 8 = 10.
            assert llm_client.total_calls == 10
            assert result.stats.llm_calls == 10
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
                planner_response=planner_response_json(
                    specs=[_make_spec(semantic="boiler")]
                ),
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


class TestRefineByReplan:
    """Phase 2: refinement re-plans from the synth hint and steers retrieval."""

    def test_replan_changes_filters_and_surfaces_the_april_doc(
        self, tmp_path: Any
    ) -> None:
        """A NeedsMore hint drives a re-plan whose date-scoped spec surfaces a
        document the first (differently-scoped) pass could not — and exactly one
        final synthesise runs."""
        settings = make_pipeline_settings(
            tmp_path, SEARCH_MAX_REFINEMENTS=1, SEARCH_GATE_JUDGE=False
        )
        store_writer = StoreWriter(settings)
        try:
            # Both documents sit on the same embedding axis, so only the date
            # filter — not the embedding geometry — decides which one each pass
            # surfaces.
            seed_pipeline_document(
                store_writer,
                document_id=1,
                title="2024 Document",
                text="A 2024 record on the boiler axis.",
                embedding=AXIS_BOILER,
                created="2024-06-15T00:00:00+00:00",
            )
            seed_pipeline_document(
                store_writer,
                document_id=2,
                title="April 2025 Payslip",
                text="Payslip for April 2025 on the boiler axis.",
                embedding=AXIS_BOILER,
                created="2025-04-15T00:00:00+00:00",
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            llm_client = ScriptedLLMClient(
                # Pass 1: scoped to 2024 — surfaces doc 1, never the April doc.
                planner_response=planner_response_json(
                    specs=[
                        _make_spec(
                            semantic="annual records",
                            date_from="2024-01-01",
                            date_to="2024-12-31",
                        )
                    ]
                ),
                # Re-plan: scoped to April 2025 — surfaces doc 2 only.
                replan_response=planner_response_json(
                    specs=[
                        _make_spec(
                            semantic="april payslip",
                            date_from="2025-04-01",
                            date_to="2025-04-30",
                        )
                    ]
                ),
                synthesiser_responses=[
                    needs_more_response_json("need the April 2025 payslip"),
                    answered_response_json(
                        "Your April 2025 payslip [2].", citations=[2]
                    ),
                ],
            )
            spy = _VectorSearchSpy(store_reader)
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=spy,
                embedding_client=make_axis_embedding_client(AXIS_BOILER),
            )
            result = core.answer("what did I earn in april?")

            # A re-plan ran, and exactly one final synthesise produced the answer.
            assert llm_client.replan_calls == 1
            assert llm_client.synthesiser_calls == 2
            assert result.stats.refined is True

            # Pass 1 was 2024-scoped; the refined pass was April-2025-scoped — a
            # genuinely different, date-scoped filter, not a blind broaden. Each
            # date-filtered spec is now paired with an unfiltered recall twin
            # (same query, filters stripped) so a wrong filter can't silently
            # exclude the answer — hence four vector searches: pass-1 filtered +
            # twin, then refined filtered + twin.
            assert len(spy.vector_filters) == 4
            assert spy.vector_filters[0].date_from == "2024-01-01"  # pass 1 filtered
            assert spy.vector_filters[1].date_from is None  # pass 1 twin
            assert spy.vector_filters[2].date_from == "2025-04-01"  # refined filtered
            assert spy.vector_filters[2].date_to == "2025-04-30"
            assert spy.vector_filters[3].date_from is None  # refined twin

            # The April doc appears only after refinement: it is the cited source.
            source_ids = {source.document_id for source in result.sources}
            assert source_ids == {2}
        finally:
            store_reader.close()

    def test_noop_guard_skips_second_retrieve_and_judge(self, tmp_path: Any) -> None:
        """When the re-plan resolves to the SAME specs as pass 1, the no-op guard
        runs exactly ONE final synthesise on the existing evidence — no second
        retrieve, no second judge."""
        settings = make_pipeline_settings(
            tmp_path, SEARCH_MAX_REFINEMENTS=1, SEARCH_GATE_JUDGE=True
        )
        store_writer = StoreWriter(settings)
        try:
            seed_pipeline_document(
                store_writer,
                document_id=1,
                title="Boiler Manual",
                text="The boiler is a Worcester Bosch Greenstar.",
                embedding=AXIS_BOILER,
            )
        finally:
            store_writer.close()

        store_reader = StoreReader(settings)
        try:
            # No replan_response → the re-plan reuses planner_response, so it
            # resolves to specs identical to pass 1: the no-op guard must fire.
            llm_client = ScriptedLLMClient(
                planner_response=planner_response_json(
                    specs=[_make_spec(semantic="boiler details")]
                ),
                judge_response='{"verdicts": [{"document_id": 1, "keep": true, '
                '"reason": "", "score": 0.9}]}',
                synthesiser_responses=[
                    needs_more_response_json("look harder"),
                    answered_response_json("The boiler is a Worcester [1].", [1]),
                ],
            )
            spy = _VectorSearchSpy(store_reader)
            core = build_search_core(
                settings=settings,
                llm_client=llm_client,
                store_reader=spy,
                embedding_client=make_axis_embedding_client(AXIS_BOILER),
            )
            result = core.answer("what boiler do I have?")

            # Re-plan happened, but resolved identical → no second retrieval.
            assert llm_client.replan_calls == 1
            assert len(spy.vector_filters) == 1  # only the pass-1 vector search
            # Exactly one judge call (pass 1) — the no-op skips the re-judge.
            assert llm_client.judge_calls == 1
            # Two synthesise calls: the exploratory one and the single final one.
            assert llm_client.synthesiser_calls == 2
            assert result.stats.refined is True
        finally:
            store_reader.close()
