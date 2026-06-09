"""Tests for the judge JSON schema and prompt (Phase 2, Task 6)."""

from __future__ import annotations

from search.prompts import JUDGE_JSON_SCHEMA, build_judge_user_message
from search.models import JudgeCandidate


def test_judge_schema_is_per_document_verdicts() -> None:
    props = JUDGE_JSON_SCHEMA["schema"]["properties"]
    assert "verdicts" in props
    item = props["verdicts"]["items"]
    assert set(item["properties"]) == {"document_id", "keep", "reason"}
    assert item["required"] == ["document_id", "keep", "reason"]
    assert JUDGE_JSON_SCHEMA["strict"] is True


def test_build_judge_user_message_omit_reasons_appends_control_line() -> None:
    """When include_reasons=False, a control-plane instruction is appended."""
    candidates = [JudgeCandidate(document_id=1, snippet="a snippet")]
    msg_with = build_judge_user_message("q?", candidates, include_reasons=True)
    msg_without = build_judge_user_message("q?", candidates, include_reasons=False)
    assert 'Leave every reason empty ("").' in msg_without
    assert 'Leave every reason empty ("").' not in msg_with


def test_build_judge_user_message_default_includes_reasons() -> None:
    candidates = [JudgeCandidate(document_id=1, snippet="a snippet")]
    msg = build_judge_user_message("q?", candidates)
    # Default is include_reasons=True — no omit-reasons control line.
    assert 'Leave every reason empty ("").' not in msg
