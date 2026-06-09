"""Tests that SearchCore threads the asker to planner, synthesiser, and cache."""

from __future__ import annotations

from typing import Any
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
    planner_response_json,
)
from tests.unit.search.conftest import build_search_core


class _CapturingLLM(ScriptedLLMClient):
    """Records every user message so a test can assert the asker reached the LLM."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.user_messages: list[str] = []

    def route(self, *, model: str, messages: list[dict], **rest: Any) -> Any:
        for m in messages:
            if m["role"] == "user":
                self.user_messages.append(m["content"])
        return super().route(model=model, messages=messages, **rest)


def _store_reader() -> MagicMock:
    sr = MagicMock()
    sr.list_facets.return_value = make_facet_set()
    sr.vector_search.return_value = [make_chunk_hit(chunk_id=1, document_id=1)]
    sr.keyword_search.return_value = []
    sr.get_documents.return_value = [make_indexed_document(document_id=1)]
    sr.get_stats.return_value = make_index_stats(document_count=1, chunk_count=1)
    return sr


def _embedding() -> MagicMock:
    ec = MagicMock()
    ec.embed.return_value = [[0.1, 0.2, 0.3]]
    return ec


def _core(llm: ScriptedLLMClient) -> Any:
    return build_search_core(
        settings=make_search_settings(SEARCH_GATE_JUDGE=False),
        llm_client=llm,
        store_reader=_store_reader(),
        embedding_client=_embedding(),
    )


def test_answer_threads_asker_to_planner_and_synthesiser() -> None:
    reset_search_result_cache()
    llm = _CapturingLLM(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
    )
    _core(llm).answer("my passport", asker="Vilmar Rosset")
    assert any("Vilmar Rosset" in m for m in llm.user_messages)  # planner
    assert sum("Vilmar Rosset" in m for m in llm.user_messages) >= 2  # planner + synth


def test_asker_isolates_the_cache() -> None:
    reset_search_result_cache()
    llm = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
    )
    core = build_search_core(
        settings=make_search_settings(
            SEARCH_GATE_JUDGE=False, SEARCH_CACHE_TTL_SECONDS=300
        ),
        llm_client=llm,
        store_reader=_store_reader(),
        embedding_client=_embedding(),
    )
    core.answer("my passport", asker="Alice")
    calls_after_alice = llm.total_calls
    # A different asker must MISS the cache (recompute), not reuse Alice's answer.
    core.answer("my passport", asker="Bob")
    assert llm.total_calls > calls_after_alice
