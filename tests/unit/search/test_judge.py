"""Tests for the RelevanceJudge stage and its data shapes."""

from __future__ import annotations

from search.models import JudgeCandidate, JudgeVerdict


def test_judge_candidate_holds_id_and_snippet() -> None:
    c = JudgeCandidate(document_id=7, snippet="boiler warranty terms")
    assert c.document_id == 7
    assert c.snippet == "boiler warranty terms"


def test_judge_verdict_defaults_not_degraded() -> None:
    v = JudgeVerdict(relevant_document_ids=frozenset({1, 2}))
    assert v.relevant_document_ids == frozenset({1, 2})
    assert v.degraded is False
