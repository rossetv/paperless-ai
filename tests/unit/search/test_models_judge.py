"""Tests for the per-document judge verdict shapes (Phase 2, Task 5)."""

from __future__ import annotations

from search.models import DocVerdict, JudgeVerdict


def test_relevant_ids_is_derived_from_kept_verdicts() -> None:
    v = JudgeVerdict(
        verdicts=(
            DocVerdict(document_id=1, keep=True, reason="matches the tax year"),
            DocVerdict(document_id=2, keep=False, reason="different correspondent"),
        )
    )
    assert v.relevant_document_ids == frozenset({1})
    assert v.degraded is False


def test_empty_verdicts_yields_empty_relevant_ids() -> None:
    assert JudgeVerdict(verdicts=()).relevant_document_ids == frozenset()


def test_doc_verdict_score_defaults_to_zero() -> None:
    # score is optional on the dataclass (back-compat); it defaults to 0.0.
    v = DocVerdict(document_id=1, keep=True, reason="")
    assert v.score == 0.0


def test_doc_verdict_carries_score() -> None:
    v = DocVerdict(document_id=1, keep=True, reason="strong match", score=0.85)
    assert v.score == 0.85


def test_judge_candidate_metadata_defaults_to_none() -> None:
    from search.models import JudgeCandidate

    c = JudgeCandidate(document_id=1, snippet="a snippet")
    assert c.title is None
    assert c.created is None
    assert c.correspondent is None
    assert c.document_type is None


def test_judge_candidate_carries_metadata() -> None:
    from search.models import JudgeCandidate

    c = JudgeCandidate(
        document_id=1,
        snippet="a snippet",
        title="Payslip",
        created="2025-04-28T00:00:00+00:00",
        correspondent="Acme Ltd",
        document_type="Payslip",
    )
    assert c.title == "Payslip"
    assert c.correspondent == "Acme Ltd"
    assert c.document_type == "Payslip"
    assert c.created == "2025-04-28T00:00:00+00:00"
