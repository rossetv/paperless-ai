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
