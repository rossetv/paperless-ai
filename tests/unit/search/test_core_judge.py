"""Tests for the Layer-3 relevance judge wired into SearchCore."""

from __future__ import annotations

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
    judge_response_json,
    planner_response_json,
)
from tests.unit.search.conftest import build_search_core


def _store_reader() -> MagicMock:
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.return_value = [
        make_chunk_hit(chunk_id=1, document_id=1),
        make_chunk_hit(chunk_id=2, document_id=2),
    ]
    store_reader.keyword_search.return_value = []
    store_reader.get_documents.return_value = [
        make_indexed_document(document_id=1),
        make_indexed_document(document_id=2),
    ]
    store_reader.get_stats.return_value = make_index_stats(
        document_count=3, chunk_count=10
    )
    return store_reader


def _embedding_client() -> MagicMock:
    embedding_client = MagicMock()
    embedding_client.embed.return_value = [[0.1, 0.2, 0.3]]
    return embedding_client


def _core(llm_client, **overrides):
    settings = make_search_settings(SEARCH_GATE_JUDGE=True, **overrides)
    return build_search_core(
        settings=settings,
        llm_client=llm_client,
        store_reader=_store_reader(),
        embedding_client=_embedding_client(),
    )


def test_judge_empty_verdict_bails_without_synthesis() -> None:
    reset_search_result_cache()
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        judge_response=judge_response_json([]),  # nothing relevant
    )
    result = _core(llm_client).answer("anything")
    assert result.outcome_kind == "no_match"
    assert llm_client.judge_calls == 1
    assert llm_client.synthesiser_calls == 0


def test_judge_filters_to_relevant_documents() -> None:
    reset_search_result_cache()
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
        judge_response=judge_response_json([1]),  # keep doc 1, drop doc 2
    )
    result = _core(llm_client).answer("warranty?")
    assert result.outcome_kind == "answered"
    assert {s.document_id for s in result.sources} == {1}
    assert llm_client.judge_calls == 1


def test_judge_off_makes_no_judge_call() -> None:
    reset_search_result_cache()
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
    )
    settings = make_search_settings(SEARCH_GATE_JUDGE=False)
    core = build_search_core(
        settings=settings,
        llm_client=llm_client,
        store_reader=_store_reader(),
        embedding_client=_embedding_client(),
    )
    core.answer("warranty?")
    assert llm_client.judge_calls == 0


def test_judge_call_counts_against_the_budget() -> None:
    reset_search_result_cache()
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
        judge_response=judge_response_json([1, 2]),
    )
    result = _core(llm_client, SEARCH_MAX_REFINEMENTS=1).answer("warranty?")
    # planner + judge + one synthesise (answered first pass).
    assert result.stats.llm_calls == 3
