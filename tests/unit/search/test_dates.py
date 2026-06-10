"""Tests for search.dates — the deterministic date-range extractor.

Each test exercises one parsing rule in isolation.  The module must be a pure
function with no I/O: it is safe to test without any mocking.
"""

from __future__ import annotations

from datetime import date

from search.dates import extract_date_range, normalise_iso_date

T = date(2026, 6, 10)


def test_month_year() -> None:
    """A '<month> YYYY' phrase extracts to the first and last day of that month."""
    assert extract_date_range("salary in April 2025", T) == ("2025-04-01", "2025-04-30")


def test_year_only() -> None:
    """A bare 4-digit year extracts to 1 Jan – 31 Dec of that year."""
    assert extract_date_range("documents from 2024", T) == ("2024-01-01", "2024-12-31")


def test_quarter() -> None:
    """A 'Q<n> YYYY' phrase extracts to the correct quarter's first and last day."""
    assert extract_date_range("Q2 2025 invoices", T) == ("2025-04-01", "2025-06-30")


def test_relative_last_month() -> None:
    """'last month' resolves relative to *today* to the previous calendar month."""
    assert extract_date_range("last month", T) == ("2026-05-01", "2026-05-31")


def test_iso_passthrough() -> None:
    """An ISO date in the text extracts as a single-day range."""
    assert extract_date_range("2025-04-25", T) == ("2025-04-25", "2025-04-25")


def test_none_when_no_temporal() -> None:
    """Text with no recognisable temporal expression returns (None, None)."""
    assert extract_date_range("my salary", T) == (None, None)


def test_normalise_iso() -> None:
    """normalise_iso_date accepts valid ISO dates/timestamps and rejects garbage."""
    assert normalise_iso_date("2025-13-99") is None
    assert normalise_iso_date("April 2025") is None
    assert normalise_iso_date("2025-04-25T00:00:00+00:00") == "2025-04-25"
    assert normalise_iso_date("2025-04-25") == "2025-04-25"


# ---------------------------------------------------------------------------
# M1: "sept" abbreviation
# ---------------------------------------------------------------------------


def test_sept_abbreviation() -> None:
    """'sept' (4-letter informal abbreviation) resolves to September."""
    assert extract_date_range("sept 2025", T) == ("2025-09-01", "2025-09-30")


# ---------------------------------------------------------------------------
# M2: malformed ISO must not widen to a year
# ---------------------------------------------------------------------------


def test_malformed_iso_returns_none_none() -> None:
    """A malformed ISO literal (e.g. "2025-13-99") must not widen to the whole year."""
    assert extract_date_range("2025-13-99", T) == (None, None)


def test_bare_year_still_works_after_m2_fix() -> None:
    """A bare 4-digit year with no following hyphen still resolves to the full year."""
    assert extract_date_range("documents from 2024", T) == ("2024-01-01", "2024-12-31")


def test_valid_iso_date_still_works_as_single_day() -> None:
    """A valid ISO date in text resolves to a single-day range (Rule 1 wins)."""
    assert extract_date_range("2025-04-25", T) == ("2025-04-25", "2025-04-25")
