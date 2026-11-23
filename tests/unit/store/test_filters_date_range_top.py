"""An end date at the top of the calendar means "no upper bound", not an error."""

from __future__ import annotations

from store.models import DocumentBrowseQuery, SearchFilters
from store.reader._filters import build_filters
from tests.helpers.store import open_reader


def _filters(
    *, date_from: str | None = None, date_to: str | None = None
) -> SearchFilters:
    return SearchFilters(
        date_from=date_from,
        date_to=date_to,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(),
    )


def test_build_filters_with_the_last_representable_day_adds_no_upper_bound() -> None:
    where, params = build_filters(_filters(date_to="9999-12-31"))

    assert where == ""
    assert params == []


def test_build_filters_with_the_last_day_keeps_the_other_bound() -> None:
    where, params = build_filters(
        _filters(date_from="0001-01-01", date_to="9999-12-31")
    )

    assert where == "WHERE d.created >= ?"
    assert params == ["0001-01-01"]


def test_build_filters_still_bounds_the_day_before_the_top() -> None:
    where, params = build_filters(_filters(date_to="9999-12-30"))

    assert where == "WHERE d.created < ?"
    assert params == ["9999-12-31"]


def test_library_listing_with_the_last_day_as_end_date_returns_every_document(
    populated_db: str,
) -> None:
    reader = open_reader(populated_db)
    page = reader.list_documents(
        DocumentBrowseQuery(
            text=None,
            date_from="0001-01-01",
            date_to="9999-12-31",
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(),
            sort="created",
            descending=True,
            offset=0,
            limit=20,
        )
    )
    reader.close()

    assert page.total == 2
