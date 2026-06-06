"""Tests for the RAG-05 result cache wired into SearchCore.answer.

A byte-identical repeat over an unchanged index makes zero further LLM calls;
a changed index version, a no-match result, and a degraded result are not
served from / written to the cache. The LLM is the ScriptedLLMClient; no real
token is spent (CODE_GUIDELINES §11.4).
"""

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
    planner_response_json,
)
from tests.unit.search.conftest import build_search_core


def _store_reader(*, document_count: int = 3, chunk_count: int = 10) -> MagicMock:
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.return_value = [
        make_chunk_hit(chunk_id=1, document_id=1)
    ]
    store_reader.keyword_search.return_value = []
    store_reader.get_documents.return_value = [make_indexed_document()]
    store_reader.get_stats.return_value = make_index_stats(
        document_count=document_count, chunk_count=chunk_count
    )
    return store_reader


def _embedding_client() -> MagicMock:
    embedding_client = MagicMock()
    embedding_client.embed.return_value = [[0.1, 0.2, 0.3]]
    return embedding_client


def _core(store_reader: MagicMock, llm_client: ScriptedLLMClient, **overrides):
    # Cache ON by default for this file; a test can override the TTL (e.g. 0).
    overrides.setdefault("SEARCH_CACHE_TTL_SECONDS", 14400)
    settings = make_search_settings(**overrides)
    return build_search_core(
        settings=settings,
        llm_client=llm_client,
        store_reader=store_reader,
        embedding_client=_embedding_client(),
    )


def _answered_client() -> ScriptedLLMClient:
    return ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("Cached [1].", citations=[1])],
    )


class TestCacheHit:
    def test_identical_repeat_makes_no_further_llm_calls(self) -> None:
        reset_search_result_cache()
        llm_client = _answered_client()
        core = _core(_store_reader(), llm_client)

        core.answer("when does my boiler warranty expire?")
        calls_after_first = llm_client.total_calls
        core.answer("when does my boiler warranty expire?")

        assert calls_after_first == 2
        assert llm_client.total_calls == 2  # second call served from cache

    def test_cache_hit_returns_the_same_answer(self) -> None:
        reset_search_result_cache()
        core = _core(_store_reader(), _answered_client())
        first = core.answer("a query")
        second = core.answer("a query")
        assert second.answer == first.answer


class TestCacheDisabled:
    def test_ttl_zero_always_recomputes(self) -> None:
        reset_search_result_cache()
        # TTL 0 → cache off → both calls recompute. Supply two synth responses.
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("first [1].", citations=[1]),
                answered_response_json("second [1].", citations=[1]),
            ],
        )
        core = _core(_store_reader(), llm_client, SEARCH_CACHE_TTL_SECONDS=0)
        core.answer("a query")
        core.answer("a query")
        assert llm_client.total_calls == 4  # 2 + 2, nothing cached


class TestIndexChangeBustsCache:
    def test_changed_counts_recompute(self) -> None:
        reset_search_result_cache()
        store_reader = _store_reader(document_count=3, chunk_count=10)
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("before [1].", citations=[1]),
                answered_response_json("after [1].", citations=[1]),
            ],
        )
        core = _core(store_reader, llm_client)
        core.answer("a query")
        # A document is indexed → counts change → next answer recomputes.
        store_reader.get_stats.return_value = make_index_stats(
            document_count=4, chunk_count=13
        )
        core.answer("a query")
        assert llm_client.total_calls == 4


class TestNoMatchNotCached:
    def test_no_match_result_is_not_cached(self) -> None:
        reset_search_result_cache()
        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        store_reader.vector_search.return_value = []
        store_reader.keyword_search.return_value = []
        store_reader.get_stats.return_value = make_index_stats(
            document_count=3, chunk_count=10
        )
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = _core(store_reader, llm_client)
        first = core.answer("matches nothing")
        # The no-match path makes only the planner call (1).
        assert llm_client.total_calls == 1
        # A repeat is NOT served from cache — planner runs again.
        second = core.answer("matches nothing")
        assert llm_client.total_calls == 2
        assert first.answer == second.answer


class TestVersionUnreadableFailsOpen:
    def test_get_stats_error_bypasses_cache(self) -> None:
        reset_search_result_cache()
        from store import StoreError

        store_reader = _store_reader()
        store_reader.get_stats.side_effect = StoreError("schema gone")
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("a [1].", citations=[1]),
                answered_response_json("b [1].", citations=[1]),
            ],
        )
        core = _core(store_reader, llm_client)
        # Must not raise; both calls run (cache cannot key itself).
        core.answer("a query")
        core.answer("a query")
        assert llm_client.total_calls == 4
