"""Tests for store._sql."""

from __future__ import annotations

import pytest

from store._sql import placeholders


def test_placeholders_builds_a_single_placeholder() -> None:
    assert placeholders(1) == "?"


def test_placeholders_builds_a_comma_separated_run() -> None:
    assert placeholders(3) == "?,?,?"


def test_placeholders_builds_a_long_run() -> None:
    assert placeholders(5) == "?,?,?,?,?"


def test_placeholders_of_zero_is_an_empty_string() -> None:
    """Zero placeholders yields an empty string — callers guard empty id lists."""
    assert placeholders(0) == ""


def test_placeholders_rejects_a_negative_count() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        placeholders(-1)


def test_placeholders_contains_only_question_marks_and_commas() -> None:
    """No value is ever interpolated — the output is structural only (§9.5)."""
    assert set(placeholders(10)) == {"?", ","}
