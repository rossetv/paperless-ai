"""Tests for classifier.content_prep."""

from __future__ import annotations

import re

from classifier.content_prep import (
    _extract_page_numbers,
    _format_page_ranges,
    _split_footer,
    truncate_content_by_chars,
    truncate_content_by_pages,
)
from classifier.constants import PAGE_HEADER_RE

class TestSplitFooter:
    """Tests for _split_footer(content)."""

    def test_content_with_footer(self):
        content = "Body text here\n\nTranscribed by model: gpt-5-mini"
        body, footer = _split_footer(content)
        assert body == "Body text here"
        assert footer == "\n\nTranscribed by model: gpt-5-mini"

    def test_content_without_footer(self):
        content = "Just body text, no footer."
        body, footer = _split_footer(content)
        assert body == "Just body text, no footer."
        assert footer == ""

    def test_multiple_footers_splits_on_last(self):
        content = (
            "Body\n\nTranscribed by model: gpt-5-mini"
            "\nMore text\n\nTranscribed by model: o4-mini"
        )
        body, footer = _split_footer(content)
        # Should split on the LAST occurrence
        assert footer == "\n\nTranscribed by model: o4-mini"
        assert "Body" in body
        assert "gpt-5-mini" in body

    def test_empty_content(self):
        body, footer = _split_footer("")
        assert body == ""
        assert footer == ""

    def test_footer_must_have_double_newline(self):
        # Single newline before "Transcribed" should not split
        content = "Body\nTranscribed by model: gpt-5-mini"
        body, footer = _split_footer(content)
        assert body == content
        assert footer == ""

class TestExtractPageNumbers:
    """Tests for _extract_page_numbers(matches)."""

    def test_normal_matches(self):
        text = "--- Page 1 ---\ntext\n--- Page 2 ---\ntext\n--- Page 3 ---"
        matches = list(PAGE_HEADER_RE.finditer(text))
        numbers = _extract_page_numbers(matches)
        assert numbers == [1, 2, 3]

    def test_non_sequential_pages(self):
        text = "--- Page 5 ---\ntext\n--- Page 10 ---"
        matches = list(PAGE_HEADER_RE.finditer(text))
        numbers = _extract_page_numbers(matches)
        assert numbers == [5, 10]

    def test_pages_with_model_annotation(self):
        text = "--- Page 1 (gpt-5-mini) ---\n--- Page 2 (o4-mini) ---"
        matches = list(PAGE_HEADER_RE.finditer(text))
        numbers = _extract_page_numbers(matches)
        assert numbers == [1, 2]

    def test_defensive_fallback_no_digits(self):
        """When a match somehow has no digits, falls back to 1-based index."""
        # Create a fake match object with no digits
        fake_pattern = re.compile(r"--- Page [A-Z]+ ---")
        text = "--- Page ABC ---"
        matches = list(fake_pattern.finditer(text))
        numbers = _extract_page_numbers(matches)
        assert numbers == [1]

class TestFormatPageRanges:
    """Tests for _format_page_ranges(page_numbers)."""

    def test_consecutive_and_gaps(self):
        assert _format_page_ranges([1, 2, 3, 5, 7, 8]) == "1-3, 5, 7-8"

    def test_empty_list(self):
        assert _format_page_ranges([]) == ""

    def test_single_page(self):
        assert _format_page_ranges([1]) == "1"

    def test_non_consecutive(self):
        assert _format_page_ranges([1, 3, 5]) == "1, 3, 5"

    def test_all_consecutive(self):
        assert _format_page_ranges([1, 2, 3, 4, 5]) == "1-5"

    def test_two_pages_consecutive(self):
        assert _format_page_ranges([1, 2]) == "1-2"

    def test_duplicates_handled(self):
        assert _format_page_ranges([1, 1, 2, 3]) == "1-3"

    def test_unsorted_input(self):
        assert _format_page_ranges([5, 1, 3, 2]) == "1-3, 5"

class TestTruncateContentByChars:
    """Tests for truncate_content_by_chars(content, max_chars)."""

    def test_within_limit_unchanged(self):
        content = "Short content."
        assert truncate_content_by_chars(content, 1000) == content

    def test_over_limit_truncated_footer_preserved(self):
        body = "A" * 100
        footer = "\n\nTranscribed by model: gpt-5-mini"
        content = body + footer
        result = truncate_content_by_chars(content, 50)
        assert result == "A" * 50 + footer
        assert len(result) < len(content)

    def test_max_chars_zero_unchanged(self):
        content = "Some content."
        assert truncate_content_by_chars(content, 0) == content

    def test_max_chars_negative_unchanged(self):
        content = "Some content."
        assert truncate_content_by_chars(content, -1) == content

    def test_body_within_limit_but_total_over(self):
        body = "A" * 50
        footer = "\n\nTranscribed by model: gpt-5-mini"
        content = body + footer
        # max_chars > body length: body is kept as-is, footer appended
        result = truncate_content_by_chars(content, 60)
        assert result == body + footer

    def test_no_footer(self):
        content = "A" * 100
        result = truncate_content_by_chars(content, 50)
        assert result == "A" * 50

    def test_exact_limit(self):
        content = "A" * 50
        assert truncate_content_by_chars(content, 50) == content

class TestTruncateContentByPages:
    """Tests for truncate_content_by_pages(content, max_pages, tail_pages, headerless_char_limit)."""

    def _make_paged_content(self, num_pages, footer=True):
        """Build content with page headers."""
        parts = []
        for i in range(1, num_pages + 1):
            parts.append(f"--- Page {i} ---\nContent of page {i}.\n")
        body = "\n".join(parts)
        if footer:
            body += "\n\nTranscribed by model: gpt-5-mini"
        return body

    def test_within_page_limit_unchanged(self):
        content = self._make_paged_content(3)
        result, note = truncate_content_by_pages(content, max_pages=5, tail_pages=1, headerless_char_limit=10000)
        assert note is None
        assert "Page 1" in result
        assert "Page 3" in result

    def test_over_page_limit_head_tail_kept(self):
        content = self._make_paged_content(10)
        result, note = truncate_content_by_pages(content, max_pages=3, tail_pages=2, headerless_char_limit=10000)
        assert note is not None
        assert "Page 1" in result
        assert "Page 2" in result
        assert "Page 3" in result
        assert "Page 9" in result
        assert "Page 10" in result
        assert "Page 5" not in result
        # Footer preserved
        assert "Transcribed by model" in result

    def test_no_page_headers_falls_back_to_char_truncation(self):
        content = "A" * 500 + "\n\nTranscribed by model: gpt-5-mini"
        result, note = truncate_content_by_pages(content, max_pages=3, tail_pages=1, headerless_char_limit=100)
        assert note is not None
        assert "characters" in note.lower() or "page headers" in note.lower()
        assert "Transcribed by model" in result

    def test_no_page_headers_within_char_limit(self):
        content = "Short text"
        result, note = truncate_content_by_pages(content, max_pages=3, tail_pages=1, headerless_char_limit=10000)
        assert result == content
        assert note is None

    def test_max_pages_zero_unchanged(self):
        content = self._make_paged_content(10)
        result, note = truncate_content_by_pages(content, max_pages=0, tail_pages=1, headerless_char_limit=10000)
        assert result == content
        assert note is None

    def test_max_pages_negative_unchanged(self):
        content = self._make_paged_content(10)
        result, note = truncate_content_by_pages(content, max_pages=-1, tail_pages=1, headerless_char_limit=10000)
        assert result == content
        assert note is None

    def test_overlapping_head_tail_all_pages_kept(self):
        content = self._make_paged_content(5)
        # max_pages=3 head + tail_pages=3 tail = covers all 5 pages
        result, note = truncate_content_by_pages(content, max_pages=3, tail_pages=3, headerless_char_limit=10000)
        assert note is None
        for i in range(1, 6):
            assert f"Page {i}" in result

    def test_footer_preserved_when_truncated(self):
        content = self._make_paged_content(10, footer=True)
        result, note = truncate_content_by_pages(content, max_pages=2, tail_pages=1, headerless_char_limit=10000)
        assert "Transcribed by model: gpt-5-mini" in result

    def test_footer_preserved_when_not_truncated(self):
        content = self._make_paged_content(3, footer=True)
        result, note = truncate_content_by_pages(content, max_pages=5, tail_pages=1, headerless_char_limit=10000)
        assert "Transcribed by model: gpt-5-mini" in result

    def test_truncation_note_includes_page_info(self):
        content = self._make_paged_content(10)
        _, note = truncate_content_by_pages(content, max_pages=2, tail_pages=1, headerless_char_limit=10000)
        assert note is not None
        assert "truncated" in note.lower()
        assert "10" in note  # total pages
