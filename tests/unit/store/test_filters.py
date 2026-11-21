"""Tests for the date-range clauses of store.reader._filters.build_filters.

``created`` is stored as a full ISO-8601 timestamp while filters are bare
``YYYY-MM-DD`` dates, so ``d.created <= date_to`` would exclude the last day of
the range. The upper bound is a half-open ``d.created < date_to + 1 day``,
which stays sargable on ``idx_documents_created``. The SQL runs against a real
in-memory SQLite database.
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

    The table is named ``d`` because the WHERE clause references ``d.created``.
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
    # The stored timestamp sorts after the bare date, so ``<= date_to`` would miss it.
    assert _match("2025-04-25T00:00:00+00:00", _make_filters(date_to="2025-04-25"))


def test_lower_bound_includes_same_day_with_tz_suffix() -> None:
    assert _match("2025-04-25T00:00:00+00:00", _make_filters(date_from="2025-04-25"))


def test_month_range_includes_mid_month_doc() -> None:
    assert _match(
        "2025-04-25T00:00:00+00:00",
        _make_filters(date_from="2025-04-01", date_to="2025-04-30"),
    )


def test_out_of_range_excluded() -> None:
    assert not _match(
        "2025-05-01T00:00:00+00:00",
        _make_filters(date_to="2025-04-30"),
    )
