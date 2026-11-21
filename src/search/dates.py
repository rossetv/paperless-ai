"""Deterministic date-range extraction from free-text query strings."""

from __future__ import annotations

import calendar
import datetime
import re

# English month names and abbreviations, matched case-insensitively.
_MONTH_NAMES: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# Longest first so the regex prefers "september" over "sep".
_MONTH_PATTERN = "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))

# Rule 1: an ISO date, e.g. "2025-04-25"
_RE_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Rule 2: quarter notation, e.g. "Q2 2025"
_RE_QUARTER = re.compile(r"\bQ([1-4])\s+(\d{4})\b", re.IGNORECASE)

# Rule 3: month + year, e.g. "April 2025" or "Apr 2025"
_RE_MONTH_YEAR = re.compile(
    rf"\b({_MONTH_PATTERN})\s+(\d{{4}})\b",
    re.IGNORECASE,
)

# Rule 4: bare 4-digit year in 1900–2199. The ``(?!-)`` lookahead stops a
# malformed date such as "2025-13-99" (rejected by Rule 1) from falling through
# here and widening the range to the whole year.
_RE_YEAR = re.compile(r"\b((?:19|20|21)\d{2})\b(?!-)")

# Rule 5: relative temporal phrases
_RE_LAST_MONTH = re.compile(r"\blast\s+month\b", re.IGNORECASE)
_RE_THIS_MONTH = re.compile(r"\bthis\s+month\b", re.IGNORECASE)
_RE_LAST_YEAR = re.compile(r"\blast\s+year\b", re.IGNORECASE)
_RE_THIS_YEAR = re.compile(r"\bthis\s+year\b", re.IGNORECASE)


def normalise_iso_date(s: str) -> str | None:
    """Return the ``YYYY-MM-DD`` date portion of *s*, or ``None`` if invalid.

    Accepts a bare ``YYYY-MM-DD`` string or a full ISO-8601 timestamp
    (``YYYY-MM-DDTHH:MM:SS±HH:MM``); a calendar error such as month 13
    returns ``None``.

    Examples::

        >>> normalise_iso_date("2025-04-25")
        '2025-04-25'
        >>> normalise_iso_date("2025-04-25T00:00:00+00:00")
        '2025-04-25'
        >>> normalise_iso_date("2025-13-99")
        None
        >>> normalise_iso_date("April 2025")
        None
    """
    if len(s) < 10:
        return None
    date_part = s[:10]
    try:
        datetime.date.fromisoformat(date_part)
    except ValueError:
        return None
    return date_part


def extract_date_range(
    text: str,
    today: datetime.date,
) -> tuple[str | None, str | None]:
    """Parse *text* for a temporal expression and return an inclusive date range.

    Returns ``YYYY-MM-DD`` strings, or ``(None, None)`` when nothing matches.
    The first matching rule wins, in the order of the ``_RE_*`` patterns above;
    relative phrases are computed from *today*.
    """
    m = _RE_ISO_DATE.search(text)
    if m:
        iso = m.group(1)
        try:
            datetime.date.fromisoformat(iso)
        except ValueError:
            pass
        else:
            return iso, iso

    m = _RE_QUARTER.search(text)
    if m:
        quarter, year = int(m.group(1)), int(m.group(2))
        first_month = (quarter - 1) * 3 + 1
        last_month = first_month + 2
        last_day = calendar.monthrange(year, last_month)[1]
        date_from = f"{year:04d}-{first_month:02d}-01"
        date_to = f"{year:04d}-{last_month:02d}-{last_day:02d}"
        return date_from, date_to

    m = _RE_MONTH_YEAR.search(text)
    if m:
        month_num = _MONTH_NAMES[m.group(1).lower()]
        year = int(m.group(2))
        last_day = calendar.monthrange(year, month_num)[1]
        date_from = f"{year:04d}-{month_num:02d}-01"
        date_to = f"{year:04d}-{month_num:02d}-{last_day:02d}"
        return date_from, date_to

    m = _RE_YEAR.search(text)
    if m:
        year = int(m.group(1))
        return f"{year:04d}-01-01", f"{year:04d}-12-31"

    if _RE_LAST_MONTH.search(text):
        if today.month == 1:
            prev_year, prev_month = today.year - 1, 12
        else:
            prev_year, prev_month = today.year, today.month - 1
        last_day = calendar.monthrange(prev_year, prev_month)[1]
        return (
            f"{prev_year:04d}-{prev_month:02d}-01",
            f"{prev_year:04d}-{prev_month:02d}-{last_day:02d}",
        )

    if _RE_THIS_MONTH.search(text):
        last_day = calendar.monthrange(today.year, today.month)[1]
        return (
            f"{today.year:04d}-{today.month:02d}-01",
            f"{today.year:04d}-{today.month:02d}-{last_day:02d}",
        )

    if _RE_LAST_YEAR.search(text):
        prev_year = today.year - 1
        return f"{prev_year:04d}-01-01", f"{prev_year:04d}-12-31"

    if _RE_THIS_YEAR.search(text):
        return f"{today.year:04d}-01-01", f"{today.year:04d}-12-31"

    return None, None
