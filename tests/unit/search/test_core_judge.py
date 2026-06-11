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
    """Explicit keep=false for every candidate → no_match without synthesis."""
    reset_search_result_cache()
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        # Explicit drop of every candidate — the new per-document judge requires
        # explicit verdicts to drop; an empty list would default to keep=True.
        judge_response=judge_response_json([], dropped_document_ids=[1, 2]),
    )
    result = _core(llm_client).answer("anything")
    assert result.outcome_kind == "no_match"
    assert llm_client.judge_calls == 1
    assert llm_client.synthesiser_calls == 0


def test_judge_filters_to_relevant_documents() -> None:
    reset_search_result_cache()
    # The answer cites BOTH documents, so the citation filter (_cited_sources)
    # alone would keep both — pinning the drop of doc 2 to the judge, not the
    # citation step. Doc 2's chunks never reach synthesis, so it has no source.
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1][2].", citations=[1, 2])],
        judge_response=judge_response_json(
            [1], dropped_document_ids=[2]
        ),  # keep doc 1, drop doc 2
    )
    result = _core(llm_client).answer("warranty?")
    assert result.outcome_kind == "answered"
    assert {s.document_id for s in result.sources} == {1}
    assert llm_client.judge_calls == 1


def test_judge_degraded_response_fails_open_and_still_synthesises() -> None:
    """A broken judge (unparseable verdict) must NEVER suppress an answer: the
    pipeline keeps every chunk and synthesises as if the judge were off. This is
    the safety net that makes default-on acceptable."""
    reset_search_result_cache()
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1][2].", citations=[1, 2])],
        judge_response="not valid json at all",  # judge fails open → keep all
    )
    result = _core(llm_client).answer("warranty?")
    assert result.outcome_kind == "answered"
    assert llm_client.judge_calls == 1
    assert llm_client.synthesiser_calls == 1
    # Both documents survived the degraded judge (nothing was dropped).
    assert {s.document_id for s in result.sources} == {1, 2}


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


# ---------------------------------------------------------------------------
# Phase 3A/identity — keep-gate tests (score is for ranking only)
# ---------------------------------------------------------------------------


def test_judge_keep_true_with_low_score_is_retained() -> None:
    """keep=true with a LOW score is retained — the score no longer gates inclusion.

    The real-world bug this fixes: a DoiT payslip scored 0.31 ("ownership is
    unclear") and was dropped, even though it genuinely belonged to the asker.
    The judge's boolean ``keep`` is now the sole gate; ``score`` is used only
    for source ranking.
    """
    reset_search_result_cache()
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1][2].", citations=[1, 2])],
        # Both kept; doc 2 has a very low score (0.31) — previously dropped by
        # the 0.5 threshold, now retained because keep=true is the sole gate.
        judge_response=judge_response_json(
            verdicts=[
                {"document_id": 1, "keep": True, "reason": "", "score": 0.9},
                {"document_id": 2, "keep": True, "reason": "", "score": 0.31},
            ]
        ),
    )
    result = _core(llm_client).answer("warranty?")
    assert result.outcome_kind == "answered"
    assert {s.document_id for s in result.sources} == {1, 2}


def test_judge_keep_false_doc_is_excluded() -> None:
    """keep=false explicitly excludes a document regardless of its score."""
    reset_search_result_cache()
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1][2].", citations=[1, 2])],
        judge_response=judge_response_json(
            verdicts=[
                {"document_id": 1, "keep": True, "reason": "", "score": 0.9},
                {
                    "document_id": 2,
                    "keep": False,
                    "reason": "not relevant",
                    "score": 0.8,
                },
            ]
        ),
    )
    result = _core(llm_client).answer("warranty?")
    assert result.outcome_kind == "answered"
    assert {s.document_id for s in result.sources} == {1}


def test_degraded_judge_keeps_all_documents() -> None:
    """A fail-open verdict keeps every document — degraded judge never blocks."""
    reset_search_result_cache()
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1][2].", citations=[1, 2])],
        judge_response="not valid json",  # → degraded fail-open
    )
    result = _core(llm_client).answer("warranty?")
    assert result.outcome_kind == "answered"
    assert {s.document_id for s in result.sources} == {1, 2}


def test_all_keep_false_bails_to_no_match() -> None:
    """Every candidate explicitly keep=false → no_match, no synthesis."""
    reset_search_result_cache()
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("unreachable", citations=[])],
        judge_response=judge_response_json(
            verdicts=[
                {"document_id": 1, "keep": False, "reason": "no", "score": 0.9},
                {"document_id": 2, "keep": False, "reason": "no", "score": 0.8},
            ]
        ),
    )
    result = _core(llm_client).answer("warranty?")
    assert result.outcome_kind == "no_match"
    assert llm_client.synthesiser_calls == 0


def test_sources_are_ranked_by_judge_score_over_rrf() -> None:
    """A higher judge score outranks a higher RRF score in the source order.

    Doc 2 has the stronger RRF (vector) score but the weaker judge score; doc 1
    has the weaker RRF but the stronger judge verdict. The final sources must
    lead with doc 1 — the judge's relevance ranking wins over the rank-based RRF.
    """
    reset_search_result_cache()
    store_reader = _store_reader()
    # Doc 2 wins on RRF (higher vector score) so it would lead under the old
    # score-only ordering.
    store_reader.vector_search.return_value = [
        make_chunk_hit(chunk_id=1, document_id=1, score=0.1),
        make_chunk_hit(chunk_id=2, document_id=2, score=0.9),
    ]
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1][2].", citations=[1, 2])],
        # Doc 1 is the stronger judge verdict (0.9 vs 0.6).
        judge_response=judge_response_json(
            verdicts=[
                {"document_id": 1, "keep": True, "reason": "", "score": 0.9},
                {"document_id": 2, "keep": True, "reason": "", "score": 0.6},
            ]
        ),
    )
    core = build_search_core(
        settings=make_search_settings(SEARCH_GATE_JUDGE=True),
        llm_client=llm_client,
        store_reader=store_reader,
        embedding_client=_embedding_client(),
    )
    result = core.answer("warranty?")
    ordered_ids = [s.document_id for s in result.sources]
    assert ordered_ids == [1, 2]


def test_sources_without_judge_scores_fall_back_to_rrf_order() -> None:
    """With the judge off, sources keep the descending-RRF order (degraded path)."""
    reset_search_result_cache()
    store_reader = _store_reader()
    store_reader.vector_search.return_value = [
        make_chunk_hit(chunk_id=1, document_id=1, score=0.1),
        make_chunk_hit(chunk_id=2, document_id=2, score=0.9),
    ]
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1][2].", citations=[1, 2])],
    )
    core = build_search_core(
        settings=make_search_settings(SEARCH_GATE_JUDGE=False),
        llm_client=llm_client,
        store_reader=store_reader,
        embedding_client=_embedding_client(),
    )
    result = core.answer("warranty?")
    # With no judge scores the order falls back entirely to the RRF/fused score,
    # descending — exactly the pre-Phase-3B behaviour.
    scores = [s.score for s in result.sources]
    assert scores == sorted(scores, reverse=True)


def test_judge_candidates_carry_resolved_metadata() -> None:
    """_judge_candidates populates title/date/correspondent/type from get_documents.

    The store look-up returns taxonomy-resolved IndexedDocuments, so the judge
    candidate's correspondent/type are names, not ids. Asserted via the judge
    user message the scripted client receives.
    """
    reset_search_result_cache()
    captured: dict[str, str] = {}

    class _CapturingClient(ScriptedLLMClient):
        def route(self, *, model, messages, **kw):
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            if "document-relevance judge" in system:
                captured["user"] = next(
                    (m["content"] for m in messages if m["role"] == "user"), ""
                )
            return super().route(model=model, messages=messages, **kw)

    llm_client = _CapturingClient(
        planner_response=planner_response_json(),
        synthesiser_responses=[answered_response_json("a [1].", citations=[1])],
        judge_response=judge_response_json([1, 2]),
    )
    store_reader = _store_reader()
    store_reader.get_documents.return_value = [
        make_indexed_document(
            document_id=1,
            title="Payslip April 2025",
            correspondent="Acme Ltd",
            document_type="Payslip",
            created="2025-04-28T00:00:00+00:00",
        ),
        make_indexed_document(document_id=2, title="Holiday photos"),
    ]
    core = build_search_core(
        settings=make_search_settings(SEARCH_GATE_JUDGE=True),
        llm_client=llm_client,
        store_reader=store_reader,
        embedding_client=_embedding_client(),
    )
    core.answer("April salary?")
    user = captured["user"]
    assert "title: Payslip April 2025" in user
    assert "from: Acme Ltd" in user
    assert "type: Payslip" in user
    assert "date: 2025-04-28T00:00:00+00:00" in user
