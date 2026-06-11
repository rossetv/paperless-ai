"""Tests for the judge JSON schema and prompt (Phase 2, Task 6)."""

from __future__ import annotations

from search.prompts import JUDGE_JSON_SCHEMA, build_judge_user_message
from search.models import JudgeCandidate


def test_judge_schema_is_per_document_verdicts() -> None:
    props = JUDGE_JSON_SCHEMA["schema"]["properties"]
    assert "verdicts" in props
    item = props["verdicts"]["items"]
    assert set(item["properties"]) == {"document_id", "keep", "reason", "score"}
    assert item["required"] == ["document_id", "keep", "reason", "score"]
    # Strict mode requires every property in ``required``; score is a number.
    assert item["properties"]["score"] == {"type": "number"}
    assert JUDGE_JSON_SCHEMA["strict"] is True


def test_build_judge_user_message_renders_candidate_metadata() -> None:
    from search.models import JudgeCandidate

    candidates = [
        JudgeCandidate(
            document_id=7,
            snippet="gross pay for the month",
            title="Payslip April 2025",
            created="2025-04-28T00:00:00+00:00",
            correspondent="Acme Ltd",
            document_type="Payslip",
        )
    ]
    msg = build_judge_user_message("April salary?", candidates)
    # The metadata line names every present field, then the snippet follows.
    assert "title: Payslip April 2025" in msg
    assert "date: 2025-04-28T00:00:00+00:00" in msg
    assert "from: Acme Ltd" in msg
    assert "type: Payslip" in msg
    assert msg.index("[7]") < msg.index("gross pay for the month")


def test_build_judge_user_message_omits_missing_metadata_fields() -> None:
    from search.models import JudgeCandidate

    # No metadata at all → a bare id header, no "None" leaking into the prompt.
    candidates = [JudgeCandidate(document_id=3, snippet="some text")]
    msg = build_judge_user_message("q?", candidates)
    assert "[3]\nsome text" in msg
    assert "title:" not in msg
    assert "None" not in msg


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


class TestJudgeIdentityAndDate:
    """build_judge_user_message injects asker + today in the control plane."""

    def test_asker_line_appears_before_the_data_fence(self) -> None:
        candidates = [JudgeCandidate(document_id=1, snippet="payslip")]
        msg = build_judge_user_message(
            "my payslip?",
            candidates,
            asker="Vilmar Rosset",
        )
        assert "Vilmar Rosset" in msg
        # Identity sits in the control plane (before the data fence).
        assert msg.index("Vilmar Rosset") < msg.index("<<<DATA ")

    def test_asker_line_mentions_ownership_resolution(self) -> None:
        candidates = [JudgeCandidate(document_id=1, snippet="payslip")]
        msg = build_judge_user_message("my payslip?", candidates, asker="Vilmar Rosset")
        lower = msg.lower()
        assert "ownership" in lower or "content" in lower

    def test_today_line_appears_before_the_data_fence(self) -> None:
        candidates = [JudgeCandidate(document_id=1, snippet="payslip")]
        msg = build_judge_user_message(
            "recent payslip?",
            candidates,
            today="2026-06-11",
        )
        assert "2026-06-11" in msg
        assert msg.index("2026-06-11") < msg.index("<<<DATA ")

    def test_both_none_produces_no_identity_or_date_injection(self) -> None:
        candidates = [JudgeCandidate(document_id=1, snippet="payslip")]
        msg_with = build_judge_user_message("q?", candidates)
        msg_without = build_judge_user_message("q?", candidates, asker=None, today=None)
        # Neither call should inject any identity or date text.
        assert "person asking" not in msg_with
        assert "Today's date" not in msg_with
        # The control plane (everything before the nonce fence) must be identical
        # — the nonce itself differs by design so the full strings are not equal.
        assert msg_with.split("<<<DATA")[0] == msg_without.split("<<<DATA")[0]

    def test_message_starts_with_question_when_no_context(self) -> None:
        """No asker or today: the message still starts with 'Question:'."""
        candidates = [JudgeCandidate(document_id=1, snippet="s")]
        msg = build_judge_user_message("q?", candidates)
        assert msg.startswith("Question:")

    def test_judge_system_prompt_still_opens_with_routing_phrase(self) -> None:
        """JUDGE_SYSTEM_PROMPT routing key is preserved (ScriptedLLMClient keys off it)."""
        from search.prompts import JUDGE_SYSTEM_PROMPT

        assert JUDGE_SYSTEM_PROMPT.startswith("You are a document-relevance judge")
