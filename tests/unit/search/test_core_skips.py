"""Tests for the default-off RAG-08 (planner skip), RAG-10 (synth skip), and
Layer 1 adequacy gate (Task 5: planner returns ClarifyNeeded).

Kill-switches default OFF, so the suite proves the gates only fire when an
operator opts in, and the skip paths spend fewer LLM calls. The LLM is the
ScriptedLLMClient; no real token is spent.
"""

from __future__ import annotations

import json as _json
from unittest.mock import MagicMock

from search.cache import reset_search_result_cache
from tests.helpers.factories import (
    make_chunk_hit,
    make_facet_set,
    make_index_stats,
    make_indexed_document,
    make_search_settings,
)
from tests.helpers.llm import (
    ScriptedLLMClient,
    answered_response_json,
    needs_more_response_json,
    planner_response_json,
)
from tests.unit.search.conftest import build_search_core


def _store_reader(*, hits=None) -> MagicMock:
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.return_value = (
        hits if hits is not None else [make_chunk_hit(chunk_id=1, document_id=1)]
    )
    store_reader.keyword_search.return_value = []
    store_reader.get_documents.return_value = [make_indexed_document()]
    store_reader.get_stats.return_value = make_index_stats(
        document_count=3, chunk_count=10
    )
    return store_reader


def _embedding_client() -> MagicMock:
    embedding_client = MagicMock()
    embedding_client.embed.return_value = [[0.1, 0.2, 0.3]]
    return embedding_client


def _core(llm_client, store_reader, **overrides):
    settings = make_search_settings(**overrides)
    return build_search_core(
        settings=settings,
        llm_client=llm_client,
        store_reader=store_reader,
        embedding_client=_embedding_client(),
    )


class TestPlannerSkipDefaultOff:
    def test_planner_runs_by_default_even_for_trivial_query(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
        )
        core = _core(llm_client, _store_reader())  # flag defaults False
        core.answer("invoices")
        assert llm_client.planner_calls == 1  # planner NOT skipped


class TestPlannerSkipWhenEnabled:
    def test_trivial_query_skips_the_planner_llm(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
        )
        core = _core(llm_client, _store_reader(), SEARCH_SKIP_PLANNER_FOR_TRIVIAL=True)
        result = core.answer("invoices")
        assert llm_client.planner_calls == 0  # planner skipped
        assert llm_client.synthesiser_calls == 1  # synth still ran
        assert len(result.sources) == 1  # retrieval used the trivial plan

    def test_non_trivial_query_still_runs_the_planner(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
        )
        core = _core(llm_client, _store_reader(), SEARCH_SKIP_PLANNER_FOR_TRIVIAL=True)
        core.answer("invoices from last year")  # temporal → not trivial
        assert llm_client.planner_calls == 1

    def test_skip_path_skips_the_planner_call(self) -> None:
        reset_search_result_cache()
        # Trivial query, planner skipped. With the default 1 refinement and a
        # synth that always wants more, the calls are exploratory + 1 refine = 2
        # synthesise calls and zero planner calls.
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[needs_more_response_json("more")],
        )
        core = _core(
            llm_client,
            _store_reader(),
            SEARCH_SKIP_PLANNER_FOR_TRIVIAL=True,
            SEARCH_MAX_REFINEMENTS=1,
        )
        result = core.answer("invoices")
        assert llm_client.planner_calls == 0
        assert llm_client.total_calls <= 2
        assert result.stats.llm_calls <= 2


# ---------------------------------------------------------------------------
# Layer 1 adequacy gate — planner returns ClarifyNeeded → core short-circuits
# ---------------------------------------------------------------------------


def _clarify_planner_response() -> str:
    """Return a clarify JSON that the planner will parse into ClarifyNeeded."""
    return _json.dumps({"clarify": {"reason": "Query is too vague."}})


class TestAdequacyGateInCore:
    """When the planner returns ClarifyNeeded the core short-circuits before
    retrieval and synthesis, returning outcome_kind='clarify'.

    Tests here use the ScriptedLLMClient so the planner is a real QueryPlanner
    that receives the clarify JSON and returns ClarifyNeeded, exercising the
    full core→planner→core path (not just a mocked planner).
    """

    def test_clarify_planner_response_produces_clarify_outcome_kind(self) -> None:
        """A planner clarify response → SearchResult.outcome_kind == 'clarify'."""
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=_clarify_planner_response(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = _core(llm_client, _store_reader(), SEARCH_GATE_ADEQUACY=True)
        result = core.answer("life")

        assert result.outcome_kind == "clarify"

    def test_clarify_result_has_the_fixed_user_facing_message(self) -> None:
        """The clarify SearchResult carries the fixed UX message, not the model's reason."""
        reset_search_result_cache()
        _FIXED_MSG = (
            "That search is a bit too broad for me to answer well. "
            "Add a detail or two, or use the filters to pick a correspondent or document type."
        )
        llm_client = ScriptedLLMClient(
            planner_response=_clarify_planner_response(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = _core(llm_client, _store_reader(), SEARCH_GATE_ADEQUACY=True)
        result = core.answer("life")

        assert result.answer == _FIXED_MSG

    def test_clarify_result_has_no_sources(self) -> None:
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=_clarify_planner_response(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = _core(llm_client, _store_reader(), SEARCH_GATE_ADEQUACY=True)
        result = core.answer("life")

        assert result.sources == ()

    def test_clarify_response_does_not_call_the_retriever(self) -> None:
        """The retriever must NOT be called when the planner returns ClarifyNeeded."""
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=_clarify_planner_response(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        store_reader = _store_reader()
        core = _core(llm_client, store_reader, SEARCH_GATE_ADEQUACY=True)
        core.answer("life")

        # Neither vector_search nor keyword_search should be called.
        store_reader.vector_search.assert_not_called()
        store_reader.keyword_search.assert_not_called()

    def test_clarify_response_makes_exactly_one_llm_call(self) -> None:
        """ClarifyNeeded short-circuits: only the planner call, no synth."""
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=_clarify_planner_response(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = _core(llm_client, _store_reader(), SEARCH_GATE_ADEQUACY=True)
        result = core.answer("life")

        assert llm_client.synthesiser_calls == 0
        assert llm_client.planner_calls == 1
        assert result.stats.llm_calls == 1

    def test_normal_query_with_gate_on_follows_answered_path(self) -> None:
        """The clarify gate must NOT fire for a query with real search intent."""
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Found it [1].", citations=[1])
            ],
        )
        core = _core(llm_client, _store_reader(), SEARCH_GATE_ADEQUACY=True)
        result = core.answer("when does my boiler warranty expire?")

        assert result.outcome_kind == "answered"
        assert llm_client.synthesiser_calls == 1

    def test_retrieve_method_also_returns_clarify_for_vague_query(self) -> None:
        """The MCP retrieve() path also short-circuits on ClarifyNeeded."""
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=_clarify_planner_response(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        store_reader = _store_reader()
        core = _core(llm_client, store_reader, SEARCH_GATE_ADEQUACY=True)
        result = core.retrieve("life")

        assert result.outcome_kind == "clarify"
        store_reader.vector_search.assert_not_called()
        store_reader.keyword_search.assert_not_called()

    def test_clarify_result_stats_reflect_one_planner_call(self) -> None:
        """SearchStats.llm_calls == 1 on the clarify path (planner only)."""
        reset_search_result_cache()
        llm_client = ScriptedLLMClient(
            planner_response=_clarify_planner_response(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = _core(llm_client, _store_reader(), SEARCH_GATE_ADEQUACY=True)
        result = core.answer("life")

        assert result.stats.llm_calls == 1
        assert result.stats.refined is False
