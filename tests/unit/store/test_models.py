"""Tests for store.models — the store-boundary dataclass shapes.

Covers the Wave 5 browse dataclasses: DocumentSummary carries page_count,
DocumentBrowseQuery carries the browse parameters, and DocumentPage carries
the rows plus the total match count. All three are frozen.
"""

from __future__ import annotations

import dataclasses

import pytest

from store.models import DocumentBrowseQuery, DocumentPage, DocumentSummary


def test_document_summary_carries_page_count() -> None:
    """DocumentSummary exposes page_count alongside the resolved names."""
    summary = DocumentSummary(
        id=1,
        title="Invoice",
        correspondent="Alpha Corp",
        document_type="Invoice",
        tags=("important",),
        created="2024-01-01T00:00:00+00:00",
        page_count=3,
    )
    assert summary.page_count == 3
    assert summary.correspondent == "Alpha Corp"

def test_document_summary_is_frozen() -> None:
    """DocumentSummary is immutable — a store-boundary shape."""
    summary = DocumentSummary(
        id=1,
        title=None,
        correspondent=None,
        document_type=None,
        tags=(),
        created=None,
        page_count=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        summary.title = "mutated"  # type: ignore[misc]

def test_document_browse_query_holds_browse_parameters() -> None:
    """DocumentBrowseQuery carries filters, sort, pagination and the text query."""
    query = DocumentBrowseQuery(
        text="gas",
        date_from="2024-01-01",
        date_to="2024-12-31",
        correspondent_id=10,
        document_type_id=20,
        tag_ids=(101, 102),
        sort="created",
        descending=True,
        offset=20,
        limit=20,
    )
    assert query.text == "gas"
    assert query.tag_ids == (101, 102)
    assert query.sort == "created"
    assert query.offset == 20

def test_document_page_carries_rows_and_total() -> None:
    """DocumentPage pairs the page rows with the full match count."""
    summary = DocumentSummary(
        id=1,
        title="Invoice",
        correspondent=None,
        document_type=None,
        tags=(),
        created=None,
        page_count=None,
    )
    page = DocumentPage(documents=(summary,), total=57, offset=0, limit=20)
    assert page.total == 57
    assert len(page.documents) == 1
    assert page.offset == 0
    assert page.limit == 20
