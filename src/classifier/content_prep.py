"""Truncation strategies for OCR text before classification."""

from __future__ import annotations

import re

from .constants import PAGE_HEADER_RE

# Matches one or more digits — used to extract page numbers from headers.
_DIGITS_RE: re.Pattern[str] = re.compile(r"\d+")


def _split_footer(content: str) -> tuple[str, str]:
    """
    Split OCR content into ``(body, footer)`` around the model-info footer.

    The footer starts at the last occurrence of ``\\n\\nTranscribed by model:``
    and runs to the end of the string.  If no footer is found, *footer* is the
    empty string.
    """
    marker = "\n\nTranscribed by model:"
    index = content.rfind(marker)
    if index == -1:
        return content, ""
    return content[:index], content[index:]


def _extract_page_numbers(matches: list[re.Match]) -> list[int]:
    """
    Return the page numbers embedded in a list of ``PAGE_HEADER_RE`` matches.

    Falls back to a 1-based sequential index when a header somehow lacks a
    number (defensive — should not happen with well-formed OCR output).
    """
    numbers: list[int] = []
    for match in matches:
        num_match = _DIGITS_RE.search(match.group(0))
        if num_match:
            numbers.append(int(num_match.group()))
        else:
            numbers.append(len(numbers) + 1)
    return numbers


def _format_page_ranges(page_numbers: list[int]) -> str:
    """
    Format a sorted list of page numbers as compact ranges.

    >>> _format_page_ranges([1, 2, 3, 5, 7, 8])
    '1-3, 5, 7-8'
    """
    if not page_numbers:
        return ""
    ordered = sorted(set(page_numbers))
    ranges: list[tuple[int, int]] = []
    start = prev = ordered[0]
    for num in ordered[1:]:
        if num == prev + 1:
            prev = num
        else:
            ranges.append((start, prev))
            start = prev = num
    ranges.append((start, prev))
    return ", ".join(
        str(s) if s == e else f"{s}-{e}" for s, e in ranges
    )


def _page_truncation_note(included_pages: list[int], total_pages: int) -> str:
    """Build a human-readable note describing which OCR pages were kept."""
    ranges = _format_page_ranges(included_pages)
    return (
        "NOTE: The document transcription below was truncated to reduce cost. "
        f"Included pages (from OCR headers): {ranges}. "
        f"Total pages with OCR headers: {total_pages}."
    )


def _headerless_truncation_note(limit: int) -> str:
    """Build a note for truncation when no page headers were found."""
    return (
        "NOTE: The document transcription below was truncated because page headers "
        f"were not found. Included the first {limit} characters."
    )


def max_char_truncation_note(limit: int) -> str:
    """Build a note for the secondary character-cap truncation."""
    return (
        "NOTE: The document transcription below was further truncated to the first "
        f"{limit} characters due to the max character limit."
    )


def truncate_content_by_chars(content: str, max_chars: int) -> str:
    """
    Truncate OCR content to *max_chars* characters, preserving the footer.

    Returns the original content unchanged when *max_chars* ≤ 0 or the
    content is already within the limit.
    """
    if max_chars <= 0 or len(content) <= max_chars:
        return content
    body, footer = _split_footer(content)
    if len(body) <= max_chars:
        return body + footer
    return body[:max_chars] + footer


def truncate_content_by_pages(
    content: str,
    max_pages: int,
    tail_pages: int,
    headerless_char_limit: int,
) -> tuple[str, str | None]:
    """
    Truncate OCR content to the first *max_pages* and last *tail_pages*.

    Uses the ``--- Page N ---`` headers injected by the OCR daemon to identify
    page boundaries.  When no headers are found, falls back to a character
    limit (*headerless_char_limit*).

    Returns:
        A ``(truncated_content, truncation_note)`` tuple.  *truncation_note*
        is ``None`` when no truncation was necessary.
    """
    if max_pages <= 0:
        return content, None

    body, footer = _split_footer(content)
    matches = list(PAGE_HEADER_RE.finditer(body))

    # No page headers → fall back to character truncation
    if not matches:
        truncated = truncate_content_by_chars(content, headerless_char_limit)
        if truncated == content:
            return content, None
        return truncated, _headerless_truncation_note(headerless_char_limit)

    page_numbers = _extract_page_numbers(matches)
    total_pages = len(matches)
    if total_pages <= max_pages:
        return body + footer, None

    # Slice the body into per-page segments.
    # The first segment starts at 0 (capturing any preamble before the first
    # page header); subsequent segments start at their header's match position.
    segments: list[str] = []
    for idx, match in enumerate(matches):
        start = 0 if idx == 0 else match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        segments.append(body[start:end])

    # Build the set of page indices to include (head + tail)
    include = set(range(min(max_pages, total_pages)))
    tail_pages = max(0, tail_pages)
    if tail_pages:
        tail_start = max(total_pages - tail_pages, 0)
        include.update(range(tail_start, total_pages))

    include_indices = sorted(include)
    if len(include_indices) >= total_pages:
        return body + footer, None

    truncated_body = "".join(segments[index] for index in include_indices)
    included_pages = [page_numbers[index] for index in include_indices]
    note = _page_truncation_note(included_pages, total_pages)
    return truncated_body + footer, note
