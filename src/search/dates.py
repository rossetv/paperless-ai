"""Deterministic date-range extraction from free-text query strings.

Provides two public functions:

- :func:`normalise_iso_date` — coerces a ``YYYY-MM-DD`` or a full ISO
  timestamp to a bare date string, rejecting anything that is not a valid date.
- :func:`extract_date_range` — scans a query string for the first recognisable
  temporal expression and returns an inclusive ``(date_from, date_to)`` pair of
  ``YYYY-MM-DD`` strings, or ``(None, None)`` when no expression is found.

No I/O.  Both functions are pure and safe to call from any layer.
"""

from __future__ import annotations

import calendar
import datetime
import re

# ---------------------------------------------------------------------------
# Month-name lookup — full English names and standard 3-letter abbreviations,
# matched case-insensitively.  Index is 1-based to match datetime.date month.
# ---------------------------------------------------------------------------
_MONTH_NAMES: dict[str, int] = {
    # Full names
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
    # 3-letter abbreviations
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

# Build the alternation of all known month tokens, longest first so the regex
# engine prefers "september" over "sep" when both could match.
_MONTH_PATTERN = "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))

# ---------------------------------------------------------------------------
# Compiled regex patterns — one per rule, ordered by priority.
# ---------------------------------------------------------------------------

# Rule 1: an ISO date, e.g. "2025-04-25"
_RE_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Rule 2: quarter notation, e.g. "Q2 2025"
_RE_QUARTER = re.compile(r"\bQ([1-4])\s+(\d{4})\b", re.IGNORECASE)

# Rule 3: month + year, e.g. "April 2025" or "Apr 2025"
_RE_MONTH_YEAR = re.compile(
    rf"\b({_MONTH_PATTERN})\s+(\d{{4}})\b",
    re.IGNORECASE,
)

# Rule 4: bare 4-digit year in the range 1900–2199.  The negative lookahead
# ``(?!-)`` prevents matching a year that is immediately followed by a hyphen,
# which means it is part of a date token (e.g. "2025-13-99") rather than a
# standalone year expression.  The ISO rule (Rule 1) handles valid date
# literals; a malformed one must not fall through to this rule and widen the
# range to the whole year.
_RE_YEAR = re.compile(r"\b((?:19|20|21)\d{2})\b(?!-)")

# Rule 5: relative temporal phrases
_RE_LAST_MONTH = re.compile(r"\blast\s+month\b", re.IGNORECASE)
_RE_THIS_MONTH = re.compile(r"\bthis\s+month\b", re.IGNORECASE)
_RE_LAST_YEAR = re.compile(r"\blast\s+year\b", re.IGNORECASE)
_RE_THIS_YEAR = re.compile(r"\bthis\s+year\b", re.IGNORECASE)


def normalise_iso_date(s: str) -> str | None:
    """Return the ``YYYY-MM-DD`` date portion of *s*, or ``None`` if invalid.

    Accepts a bare ``YYYY-MM-DD`` string or a full ISO-8601 timestamp
    (``YYYY-MM-DDTHH:MM:SS±HH:MM``).  Takes the first 10 characters and
    validates them with :func:`datetime.date.fromisoformat`, so any calendar
    error (e.g. month 13, day 99) returns ``None``.  Any input shorter than
    10 characters or not starting with a date-like prefix also returns ``None``.

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

    Returns a ``(date_from, date_to)`` pair of ``YYYY-MM-DD`` strings, or
    ``(None, None)`` when no recognisable expression is found.  The first
    matching rule wins; rules are tried in priority order:

    1. **ISO date** — a ``YYYY-MM-DD`` literal anywhere in the text resolves to
       a single-day range ``(date, date)``.
    2. **Quarter** — ``Q<1-4> YYYY`` resolves to the first and last day of that
       quarter.
    3. **Month + year** — a full or 3-letter English month name followed by a
       4-digit year resolves to the first and last day of that month.
    4. **Year** — a bare 4-digit year in 1900–2199 resolves to
       ``YYYY-01-01`` / ``YYYY-12-31``.
    5. **Relative phrases** — ``last month``, ``this month``, ``last year``,
       ``this year`` are computed from *today*.

    Args:
        text:  The raw user query string.
        today: The reference date for relative expressions.  Injected so the
               function is deterministic in tests.

    Returns:
        A pair ``(date_from, date_to)`` of ``YYYY-MM-DD`` strings, or
        ``(None, None)`` when no temporal expression is recognised.
    """
    # Rule 1 — ISO date literal.
    m = _RE_ISO_DATE.search(text)
    if m:
        iso = m.group(1)
        # Validate: must be a real calendar date.
        try:
            datetime.date.fromisoformat(iso)
        except ValueError:
            pass
        else:
            return iso, iso

    # Rule 2 — quarter notation.
    m = _RE_QUARTER.search(text)
    if m:
        quarter, year = int(m.group(1)), int(m.group(2))
        # Each quarter spans exactly 3 months starting at month (quarter-1)*3+1.
        first_month = (quarter - 1) * 3 + 1
        last_month = first_month + 2
        last_day = calendar.monthrange(year, last_month)[1]
        date_from = f"{year:04d}-{first_month:02d}-01"
        date_to = f"{year:04d}-{last_month:02d}-{last_day:02d}"
        return date_from, date_to

    # Rule 3 — named month + year.
    m = _RE_MONTH_YEAR.search(text)
    if m:
        month_num = _MONTH_NAMES[m.group(1).lower()]
        year = int(m.group(2))
        last_day = calendar.monthrange(year, month_num)[1]
        date_from = f"{year:04d}-{month_num:02d}-01"
        date_to = f"{year:04d}-{month_num:02d}-{last_day:02d}"
        return date_from, date_to

    # Rule 4 — bare 4-digit year (1900–2199).
    m = _RE_YEAR.search(text)
    if m:
        year = int(m.group(1))
        return f"{year:04d}-01-01", f"{year:04d}-12-31"

    # Rule 5 — relative phrases.
    if _RE_LAST_MONTH.search(text):
        # First day of the previous month; last day via monthrange.
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
