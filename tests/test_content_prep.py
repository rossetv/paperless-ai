"""Tests for classifier.content_prep — truncation and footer handling."""

from classifier.content_prep import (
    _extract_page_numbers,
    _format_page_ranges,
    _split_footer,
    max_char_truncation_note,
    truncate_content_by_chars,
    truncate_content_by_pages,
)
from classifier.constants import PAGE_HEADER_RE


# ---------------------------------------------------------------------------
# _split_footer
# ---------------------------------------------------------------------------


def test_split_footer_present():
    content = "body text\n\nTranscribed by model: gpt-5"
    body, footer = _split_footer(content)
    assert body == "body text"
    assert footer == "\n\nTranscribed by model: gpt-5"


def test_split_footer_absent():
    content = "just body text"
    body, footer = _split_footer(content)
    assert body == "just body text"
    assert footer == ""


def test_split_footer_uses_last_occurrence():
    content = (
        "text\n\nTranscribed by model: first\n\n"
        "more text\n\nTranscribed by model: second"
    )
    body, footer = _split_footer(content)
    assert footer == "\n\nTranscribed by model: second"
    assert "first" in body


# ---------------------------------------------------------------------------
# _extract_page_numbers
# ---------------------------------------------------------------------------


def test_extract_page_numbers():
    body = "--- Page 1 ---\nA\n--- Page 3 ---\nB\n--- Page 5 (gpt-5) ---\nC"
    matches = list(PAGE_HEADER_RE.finditer(body))
    numbers = _extract_page_numbers(matches)
    assert numbers == [1, 3, 5]


# ---------------------------------------------------------------------------
# _format_page_ranges
# ---------------------------------------------------------------------------


def test_format_page_ranges_consecutive():
    assert _format_page_ranges([1, 2, 3]) == "1-3"


def test_format_page_ranges_mixed():
    assert _format_page_ranges([1, 2, 3, 5, 7, 8]) == "1-3, 5, 7-8"


def test_format_page_ranges_single():
    assert _format_page_ranges([5]) == "5"


def test_format_page_ranges_empty():
    assert _format_page_ranges([]) == ""


def test_format_page_ranges_duplicates():
    assert _format_page_ranges([1, 1, 2, 2, 3]) == "1-3"


# ---------------------------------------------------------------------------
# truncate_content_by_chars
# ---------------------------------------------------------------------------


def test_truncate_by_chars_preserves_footer():
    content = "A" * 100 + "\n\nTranscribed by model: gpt-5"
    result = truncate_content_by_chars(content, 50)
    assert result.startswith("A" * 50)
    assert result.endswith("Transcribed by model: gpt-5")


def test_truncate_by_chars_no_truncation_needed():
    content = "short"
    result = truncate_content_by_chars(content, 100)
    assert result == content


def test_truncate_by_chars_zero_max():
    content = "A" * 100
    result = truncate_content_by_chars(content, 0)
    assert result == content


def test_truncate_by_chars_no_footer():
    content = "A" * 100
    result = truncate_content_by_chars(content, 50)
    assert result == "A" * 50


def test_truncate_by_chars_body_within_limit_with_footer():
    content = "A" * 10 + "\n\nTranscribed by model: gpt-5"
    result = truncate_content_by_chars(content, 20)
    # Body (10 chars) ≤ max_chars (20), so body + footer returned
    assert "A" * 10 in result
    assert "Transcribed by model: gpt-5" in result


# ---------------------------------------------------------------------------
# truncate_content_by_pages — edge cases
# ---------------------------------------------------------------------------


def test_truncate_by_pages_zero_max_pages():
    content = "--- Page 1 ---\nA\n--- Page 2 ---\nB"
    result, note = truncate_content_by_pages(content, 0, 0, 1000)
    assert result == content
    assert note is None


def test_truncate_by_pages_within_limit():
    content = "--- Page 1 ---\nA\n\n--- Page 2 ---\nB"
    result, note = truncate_content_by_pages(content, 5, 0, 1000)
    assert "--- Page 1 ---" in result
    assert "--- Page 2 ---" in result
    assert note is None


def test_truncate_by_pages_tail_overlap_returns_all():
    """When head + tail pages cover everything, no truncation."""
    content = (
        "--- Page 1 ---\nA\n\n"
        "--- Page 2 ---\nB\n\n"
        "--- Page 3 ---\nC\n\n"
        "\n\nTranscribed by model: gpt-5"
    )
    result, note = truncate_content_by_pages(content, 2, 2, 1000)
    assert "--- Page 1 ---" in result
    assert "--- Page 2 ---" in result
    assert "--- Page 3 ---" in result
    assert note is None


# ---------------------------------------------------------------------------
# max_char_truncation_note
# ---------------------------------------------------------------------------


def test_max_char_truncation_note_format():
    note = max_char_truncation_note(5000)
    assert "5000" in note
    assert "characters" in note


# ---------------------------------------------------------------------------
# Line 58: _extract_page_numbers fallback when match has no digits
# ---------------------------------------------------------------------------


class _FakeMatch:
    """Simulates a regex match whose group(0) returns arbitrary text."""

    def __init__(self, text):
        self._text = text

    def group(self, n=0):
        return self._text


def test_extract_page_numbers_no_digits_fallback():
    """When a page header match contains no digits, fall back to 1-based index."""
    matches = [_FakeMatch("--- Page --- "), _FakeMatch("--- Page ---")]
    numbers = _extract_page_numbers(matches)
    # First match: no digits → len(numbers)+1 = 1
    # Second match: no digits → len(numbers)+1 = 2
    assert numbers == [1, 2]


def test_extract_page_numbers_mixed_digits_and_no_digits():
    """Mix of normal matches (with digits) and one without digits."""
    matches = [
        _FakeMatch("--- Page 5 ---"),
        _FakeMatch("--- Page ---"),   # no digits
        _FakeMatch("--- Page 10 ---"),
    ]
    numbers = _extract_page_numbers(matches)
    # First: digit 5
    # Second: no digits → len(numbers)+1 = 2
    # Third: digit 10
    assert numbers == [5, 2, 10]
