"""Tests for the per-phase trace + cost telemetry wired through SearchCore.

The core threads an optional ``on_event`` callback and a ``_Telemetry``
accumulator through the pipeline: every executed phase emits a ``PhaseStart``
then a ``PhaseRecord``, and the assembled ``SearchTrace`` + ``CostSummary`` ride
on ``SearchStats``. ``on_event=None`` (the default the existing tests use) keeps
the pipeline byte-identical bar the now-populated trace/cost on the result.

These tests reuse the scripted-LLM wiring from :mod:`test_core` (``build_search_core``
with a ``ScriptedLLMClient``): the trace is asserted from the emitted events and
from ``result.stats.trace`` so the two are pinned to agree.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from search.cache import reset_search_result_cache
from search.models import PhaseRecord
from search.trace import PhaseStart
from tests.helpers.factories import (
    make_chunk_hit,
    make_facet_set,
    make_index_stats,
    make_indexed_document,
    make_search_settings,
)
from tests.helpers.llm import (
    ScriptedLLMClient,
    _make_spec,
    answered_response_json,
    judge_response_json,
    needs_more_response_json,
    planner_response_json,
)
from tests.unit.search.conftest import build_search_core


def _store_reader(*, vector_hits=None, documents=None) -> MagicMock:
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.return_value = (
        vector_hits
        if vector_hits is not None
        else [make_chunk_hit(chunk_id=1, document_id=1)]
    )
    store_reader.keyword_search.return_value = []
    store_reader.get_documents.return_value = (
        documents if documents is not None else [make_indexed_document(document_id=1)]
    )
    store_reader.get_stats.return_value = make_index_stats(
        document_count=3, chunk_count=10
    )
    return store_reader


def _embedding_client() -> MagicMock:
    embedding_client = MagicMock()
    embedding_client.embed.return_value = [[0.1, 0.2, 0.3]]
    return embedding_client


def _phases(events: list) -> list[str]:
    return [e.phase for e in events if isinstance(e, PhaseRecord)]


def _records(events: list) -> list[PhaseRecord]:
    return [e for e in events if isinstance(e, PhaseRecord)]


class TestPhaseEmission:
    def test_normal_query_emits_plan_retrieve_gate_synthesise_in_order(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        # make_search_settings defaults SEARCH_GATE_RELEVANCE=True (production
        # default), so the gate phase fires — inert at min_similarity 0.0.
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        events: list = []
        result = core.answer("a normal query", on_event=events.append)

        assert _phases(events) == [
            "plan",
            "resolve",
            "retrieve",
            "gate",
            "synthesise",
        ]
        # Every PhaseRecord is preceded by its PhaseStart with the same phase.
        starts = [e for e in events if isinstance(e, PhaseStart)]
        assert [s.phase for s in starts] == [
            "plan",
            "resolve",
            "retrieve",
            "gate",
            "synthesise",
        ]
        # The result's trace mirrors the emitted records exactly.
        assert tuple(p.phase for p in result.stats.trace.phases) == (
            "plan",
            "resolve",
            "retrieve",
            "gate",
            "synthesise",
        )

    def test_trace_matches_emitted_records(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        events: list = []
        result = core.answer("a query", on_event=events.append)
        emitted = _records(events)
        assert list(result.stats.trace.phases) == emitted

    def test_default_on_event_still_populates_trace_and_cost(self) -> None:
        """No callback → no emission, but the result still carries trace + cost."""
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        result = core.answer("a query")
        assert tuple(p.phase for p in result.stats.trace.phases) == (
            "plan",
            "resolve",
            "retrieve",
            "gate",
            "synthesise",
        )
        # planner + synthesise both made a (mocked) call → two priced calls
        # (the gate is not an LLM call).
        assert result.stats.cost.llm_calls == 2
        # gpt-5.4-mini / gpt-5.4 are priced; zero tokens → $0.0, not None.
        assert result.stats.cost.usd == 0.0
        assert result.stats.cost.local is False


class TestPlanDetail:
    def test_plan_detail_carries_rewritten_query_and_filters(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(
                specs=[
                    _make_spec(
                        semantic="rewritten boiler warranty", correspondent="npower"
                    )
                ]
            ),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("boiler", on_event=events.append)
        plan_rec = next(p for p in _records(events) if p.phase == "plan")
        assert plan_rec.detail["rewritten_query"] == "rewritten boiler warranty"
        assert plan_rec.detail["filters"] == {"correspondent": "npower"}
        assert plan_rec.detail["skipped_trivial"] is False
        # The plan made one LLM call → its phase carries tokens.
        assert plan_rec.tokens is not None

    def test_skipped_trivial_plan_makes_no_llm_call(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_SKIP_PLANNER_FOR_TRIVIAL=True),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("boiler", on_event=events.append)
        plan_rec = next(p for p in _records(events) if p.phase == "plan")
        assert plan_rec.detail["skipped_trivial"] is True
        # No LLM call on the trivial-skip path → no tokens on the plan phase.
        assert plan_rec.tokens is None
        assert llm_client.planner_calls == 0


class TestRetrieveDetail:
    def test_retrieve_detail_reports_counts_and_not_broadened(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("a query", on_event=events.append)
        rec = next(p for p in _records(events) if p.phase == "retrieve")
        assert rec.detail["chunk_count"] == 1
        assert rec.detail["doc_count"] == 1
        assert rec.detail["broadened"] is False
        assert rec.tokens is None  # retrieval is not an LLM call

    def test_retrieve_detail_marks_broadened_on_second_pass(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(
                specs=[_make_spec(correspondent="npower")]
            ),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        store_reader.vector_search.side_effect = [
            [],
            [make_chunk_hit(chunk_id=1, document_id=1)],
        ]
        store_reader.keyword_search.return_value = []
        store_reader.get_documents.return_value = [make_indexed_document(document_id=1)]
        store_reader.get_stats.return_value = make_index_stats(
            document_count=3, chunk_count=10
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("npower bill", on_event=events.append)
        rec = next(p for p in _records(events) if p.phase == "retrieve")
        assert rec.detail["broadened"] is True


class TestGateDetail:
    def test_gate_phase_emitted_with_signal_detail(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        # Gate ON but min_similarity 0.0 (default) keeps it inert → proceeds.
        core = build_search_core(
            settings=make_search_settings(SEARCH_GATE_RELEVANCE=True),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("a query", on_event=events.append)
        rec = next(p for p in _records(events) if p.phase == "gate")
        assert rec.detail["rejected"] is False
        assert rec.detail["min_similarity"] == 0.0
        assert "best_similarity" in rec.detail
        assert "has_keyword_hit" in rec.detail
        assert rec.tokens is None

    def test_no_gate_phase_when_disabled(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_GATE_RELEVANCE=False),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("a query", on_event=events.append)
        assert "gate" not in _phases(events)

    def test_gate_rejection_emits_gate_then_no_match(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        # A high floor (0.99) above the synthetic hit's similarity (~0.667) with
        # no keyword hit makes the gate reject → no_match, no synthesis.
        core = build_search_core(
            settings=make_search_settings(
                SEARCH_GATE_RELEVANCE=True, SEARCH_RELEVANCE_MIN_SIMILARITY=0.99
            ),
            llm_client=llm_client,
            store_reader=_store_reader(
                vector_hits=[make_chunk_hit(chunk_id=1, document_id=1)]
            ),
            embedding_client=_embedding_client(),
        )
        events: list = []
        result = core.answer("a query", on_event=events.append)
        # The gate phase is present and marks the rejection; synthesis never ran.
        gate_rec = next(p for p in _records(events) if p.phase == "gate")
        assert gate_rec.detail["rejected"] is True
        assert _phases(events) == ["plan", "resolve", "retrieve", "gate"]
        assert result.outcome_kind == "no_match"
        # The rejection short-circuits before synthesis.
        assert llm_client.synthesiser_calls == 0


class TestJudgeDetail:
    def test_judge_phase_carries_per_document_verdicts(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("a [1][2].", citations=[1, 2])
            ],
            judge_response=judge_response_json([1], dropped_document_ids=[2]),
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_GATE_JUDGE=True),
            llm_client=llm_client,
            store_reader=_store_reader(
                vector_hits=[
                    make_chunk_hit(chunk_id=1, document_id=1),
                    make_chunk_hit(chunk_id=2, document_id=2),
                ],
                documents=[
                    make_indexed_document(document_id=1),
                    make_indexed_document(document_id=2),
                ],
            ),
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("warranty?", on_event=events.append)
        rec = next(p for p in _records(events) if p.phase == "judge")
        assert rec.detail["degraded"] is False
        assert rec.detail["bailed"] is False
        verdicts = {v["doc_id"]: v for v in rec.detail["verdicts"]}
        assert verdicts[1]["keep"] is True
        assert verdicts[2]["keep"] is False
        assert verdicts[2]["reason"] == "not relevant"
        # title resolves to None when not readily available from the chunks.
        assert verdicts[1]["title"] is None
        # The judge made one LLM call → its phase carries tokens.
        assert rec.tokens is not None

    def test_judge_bail_marks_bailed_and_returns_no_match(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
            judge_response=judge_response_json([], dropped_document_ids=[1, 2]),
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_GATE_JUDGE=True),
            llm_client=llm_client,
            store_reader=_store_reader(
                vector_hits=[
                    make_chunk_hit(chunk_id=1, document_id=1),
                    make_chunk_hit(chunk_id=2, document_id=2),
                ],
            ),
            embedding_client=_embedding_client(),
        )
        events: list = []
        result = core.answer("warranty?", on_event=events.append)
        rec = next(p for p in _records(events) if p.phase == "judge")
        assert rec.detail["bailed"] is True
        assert result.outcome_kind == "no_match"
        # The judge bail short-circuits before synthesis.
        assert "synthesise" not in _phases(events)


class TestSynthesiseAndRefineDetail:
    def test_refine_emits_refine_and_second_synthesise(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                needs_more_response_json("Broaden the date range."),
                answered_response_json("Final answer [2].", citations=[2]),
            ],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_MAX_REFINEMENTS=1),
            llm_client=llm_client,
            store_reader=_store_reader(
                vector_hits=[make_chunk_hit(chunk_id=2, document_id=2)],
                documents=[make_indexed_document(document_id=2)],
            ),
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("a query", on_event=events.append)
        phases = _phases(events)
        # plan, resolve, retrieve, gate (default-on), synthesise (exploratory),
        # replan (Phase 2), refine (the marker), synthesise (final). With no
        # scripted re-plan response the re-plan resolves to the same specs as
        # pass 1 — the no-op path — so the refine marker reports noop and no
        # second retrieve/judge phase is emitted.
        assert phases == [
            "plan",
            "resolve",
            "retrieve",
            "gate",
            "synthesise",
            "replan",
            "refine",
            "synthesise",
        ]
        synth_recs = [p for p in _records(events) if p.phase == "synthesise"]
        assert synth_recs[0].detail["needs_more"] is True
        assert synth_recs[0].detail["mode"] == "exploratory"
        assert synth_recs[1].detail["needs_more"] is False
        assert synth_recs[1].detail["mode"] == "final"
        replan_rec = next(p for p in _records(events) if p.phase == "replan")
        assert replan_rec.detail["hint"] == "Broaden the date range."
        refine_rec = next(p for p in _records(events) if p.phase == "refine")
        assert refine_rec.detail["gap"] == "Broaden the date range."
        assert refine_rec.detail["noop"] is True
        assert refine_rec.detail["new_specs"] == []
        assert "no new searches" in refine_rec.detail["action"]

    def test_synthesise_detail_on_normal_query(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("a query", on_event=events.append)
        rec = next(p for p in _records(events) if p.phase == "synthesise")
        assert rec.detail == {"mode": "exploratory", "needs_more": False}


class TestClarifyAndNoMatchTrace:
    def test_layer0_clarify_has_empty_trace(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("x", citations=[])],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_MIN_QUERY_CHARS=5),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        events: list = []
        result = core.answer("ab", on_event=events.append)  # below the floor
        assert result.outcome_kind == "clarify"
        assert result.stats.trace.phases == ()
        assert result.stats.cost.llm_calls == 0
        assert _phases(events) == []

    def test_no_match_trace_carries_plan_and_retrieve(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        store_reader.vector_search.return_value = []
        store_reader.keyword_search.return_value = []
        store_reader.get_stats.return_value = make_index_stats(
            document_count=3, chunk_count=10
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        events: list = []
        result = core.answer("nothing matches", on_event=events.append)
        assert result.outcome_kind == "no_match"
        assert tuple(p.phase for p in result.stats.trace.phases) == (
            "plan",
            "resolve",
            "retrieve",
        )


class TestRetrieveSourcesOnlyTrace:
    def test_retrieve_method_attaches_plan_and_retrieve_trace(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("unused", citations=[])],
        )
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        events: list = []
        result = core.retrieve("a query", on_event=events.append)
        assert _phases(events) == ["plan", "resolve", "retrieve"]
        assert tuple(p.phase for p in result.stats.trace.phases) == (
            "plan",
            "resolve",
            "retrieve",
        )
        # Only the planner call is priced (no synthesis in sources-only mode).
        assert result.stats.cost.llm_calls == 1


class TestCacheHitPhase:
    def test_cache_hit_emits_cache_phase_and_returns_cached(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("A real answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            # TTL > 0 so the cache is live; a cacheable answer is stored.
            settings=make_search_settings(SEARCH_CACHE_TTL_SECONDS=300),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        first = core.answer("a cacheable query")
        # Second call hits the cache.
        events: list = []
        second = core.answer("a cacheable query", on_event=events.append)
        assert second is first  # the exact cached object
        recs = _records(events)
        assert [r.phase for r in recs] == ["cache"]
        assert recs[0].detail["from_cache"] is True
        assert recs[0].cost is not None and recs[0].cost.usd == 0.0
        assert recs[0].tokens is None
        # A PhaseStart for the cache phase precedes the record.
        starts = [e for e in events if isinstance(e, PhaseStart)]
        assert [s.phase for s in starts] == ["cache"]

    def test_cache_hit_without_callback_does_not_emit(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("A real answer [1].", citations=[1])
            ],
        )
        core = build_search_core(
            settings=make_search_settings(SEARCH_CACHE_TTL_SECONDS=300),
            llm_client=llm_client,
            store_reader=_store_reader(),
            embedding_client=_embedding_client(),
        )
        first = core.answer("a cacheable query")
        second = core.answer("a cacheable query")  # no on_event → no emission
        assert second is first
