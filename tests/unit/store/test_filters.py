"""Tests for the date-range bug fix in store.reader._filters.build_filters.

Documents in index.db store ``created`` as a full ISO-8601 timestamp with a
timezone suffix, e.g. ``"2025-04-25T00:00:00+00:00"``.  The date filters
supplied by the search pipeline are bare ``YYYY-MM-DD`` strings.  A naïve
lexicographic comparison (``d.created >= ?``) fails because the ``T…``
suffix sorts *after* the bare date string, meaning the upper bound silently
excludes every document dated on the last day of the range.

The fix keeps a sargable plain-column comparison: ``d.created >= ?`` for the
lower bound, and a half-open ``d.created < ?`` for the upper bound where the
parameter is ``date_to`` advanced by one day.  This includes every timestamp
on ``date_to`` while leaving ``idx_documents_created`` usable (a ``date()``
wrapper would be non-sargable).  These tests confirm the correct behaviour by
running the actual SQL against a real in-memory SQLite database.
"""

from __future__ import annotations

import sqlite3

from store.models import SearchFilters
from store.reader._filters import build_filters


def _make_filters(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> SearchFilters:
    """Construct a :class:`SearchFilters` with only the date fields set."""
    return SearchFilters(
        date_from=date_from,
        date_to=date_to,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(),
    )


def _match(created: str, filters: SearchFilters) -> bool:
    """Return True if a row with *created* passes the SQL produced by *filters*.

    Creates a single-row in-memory SQLite table aliased to ``d`` and executes
    the WHERE clause returned by :func:`build_filters`.  The clause references
    ``d.created``, so the FROM clause must use the alias ``d``.
    """
    where, params = build_filters(filters)
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE d (created TEXT)")
    db.execute("INSERT INTO d VALUES (?)", (created,))
    if where:
        sql = f"SELECT 1 FROM d {where}"
    else:
        sql = "SELECT 1 FROM d"
    return db.execute(sql, params).fetchone() is not None


def test_upper_bound_includes_same_day_with_tz_suffix() -> None:
    """A stored timestamp on the bound date must be included by date_to."""
    # "2025-04-25T00:00:00+00:00" must match date_to="2025-04-25".
    # With the naïve ``d.created <= ?`` the stored timestamp sorts *after*
    # the bare date string and the row is excluded — the bug this test pins.
    assert _match("2025-04-25T00:00:00+00:00", _make_filters(date_to="2025-04-25"))


def test_lower_bound_includes_same_day_with_tz_suffix() -> None:
    """A stored timestamp on the bound date must be included by date_from."""
    assert _match("2025-04-25T00:00:00+00:00", _make_filters(date_from="2025-04-25"))


def test_month_range_includes_mid_month_doc() -> None:
    """A full-month range must include a document from a mid-month timestamp."""
    assert _match(
        "2025-04-25T00:00:00+00:00",
        _make_filters(date_from="2025-04-01", date_to="2025-04-30"),
    )


def test_out_of_range_excluded() -> None:
    """A document outside the upper bound must not be returned."""
    assert not _match(
        "2025-05-01T00:00:00+00:00",
        _make_filters(date_to="2025-04-30"),
    )
