"""Tests for the default-off RAG-08 (planner skip) and RAG-10 (synth skip).

Both kill-switches default OFF, so the suite proves the gates only fire when an
operator opts in, and the 3-LLM-call ceiling holds on the skip paths. The LLM
is the ScriptedLLMClient; no real token is spent.
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
        core = _core(
            llm_client, _store_reader(), SEARCH_SKIP_PLANNER_FOR_TRIVIAL=True
        )
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
        core = _core(
            llm_client, _store_reader(), SEARCH_SKIP_PLANNER_FOR_TRIVIAL=True
        )
        core.answer("invoices from last year")  # temporal → not trivial
        assert llm_client.planner_calls == 1

    def test_skip_path_keeps_the_three_call_ceiling(self) -> None:
        reset_search_result_cache()
        # Trivial query, planner skipped, synth always NeedsMore: at most 2 synth
        # calls (exploratory + 1 refine). Total ≤ 2, never a 4th call.
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[needs_more_response_json("more")],
        )
        core = _core(
            llm_client,
            _store_reader(),
            SEARCH_SKIP_PLANNER_FOR_TRIVIAL=True,
            SEARCH_MAX_REFINEMENTS=99,
        )
        result = core.answer("invoices")
        assert llm_client.planner_calls == 0
        assert llm_client.total_calls <= 2
        assert result.stats.llm_calls <= 2


class TestWeakRetrievalSkipDefaultOff:
    def test_synth_runs_by_default_on_weak_retrieval(self) -> None:
        reset_search_result_cache()
        # One low-score chunk; flag default off → synth still runs.
        weak = [make_chunk_hit(chunk_id=1, document_id=1, score=0.001)]
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
        )
        core = _core(llm_client, _store_reader(hits=weak))
        core.answer("a query")
        assert llm_client.synthesiser_calls == 1  # synth NOT skipped


class TestWeakRetrievalSkipWhenEnabled:
    def test_flag_on_default_thresholds_still_synthesises(self) -> None:
        reset_search_result_cache()
        weak = [make_chunk_hit(chunk_id=1, document_id=1, score=0.001)]
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
        )
        # Flag on but thresholds at no-op defaults (min chunks 1, min score 0.0):
        # one chunk is >= 1 and any score >= 0.0, so retrieval is NOT weak.
        core = _core(
            llm_client,
            _store_reader(hits=weak),
            SEARCH_SKIP_SYNTH_ON_WEAK_RETRIEVAL=True,
        )
        core.answer("a query")
        assert llm_client.synthesiser_calls == 1

    def test_below_min_score_returns_no_match_without_synth(self) -> None:
        reset_search_result_cache()
        # Best fused score will be ~1/61 ≈ 0.0164 for a single top-rank chunk.
        # Set the min-score threshold above that so retrieval reads as weak.
        weak = [make_chunk_hit(chunk_id=1, document_id=1, score=0.001)]
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = _core(
            llm_client,
            _store_reader(hits=weak),
            SEARCH_SKIP_SYNTH_ON_WEAK_RETRIEVAL=True,
            SEARCH_WEAK_RETRIEVAL_MIN_SCORE=0.5,  # above any single-chunk RRF score
        )
        result = core.answer("a query")
        assert llm_client.synthesiser_calls == 0  # synth skipped
        assert result.sources == ()  # no-match result reused
        assert result.answer != ""  # the no-match answer is set

    def test_below_min_chunks_returns_no_match_without_synth(self) -> None:
        reset_search_result_cache()
        weak = [make_chunk_hit(chunk_id=1, document_id=1, score=0.5)]
        llm_client = ScriptedLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        )
        core = _core(
            llm_client,
            _store_reader(hits=weak),
            SEARCH_SKIP_SYNTH_ON_WEAK_RETRIEVAL=True,
            SEARCH_WEAK_RETRIEVAL_MIN_CHUNKS=2,  # one chunk < 2 → weak
        )
        result = core.answer("a query")
        assert llm_client.synthesiser_calls == 0
        assert result.sources == ()
