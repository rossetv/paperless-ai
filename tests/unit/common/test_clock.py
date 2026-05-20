"""Tests for common.clock."""

from __future__ import annotations

from datetime import datetime

from common.clock import utc_now_iso


def test_utc_now_iso_returns_a_parseable_iso_string() -> None:
    """The returned string round-trips through datetime.fromisoformat."""
    parsed = datetime.fromisoformat(utc_now_iso())
    assert isinstance(parsed, datetime)


def test_utc_now_iso_is_timezone_aware() -> None:
    """The timestamp carries a UTC offset so values compare unambiguously."""
    parsed = datetime.fromisoformat(utc_now_iso())
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_utc_now_iso_is_monotonic_across_calls() -> None:
    """A later call never produces an earlier timestamp."""
    first = utc_now_iso()
    second = utc_now_iso()
    assert second >= first
