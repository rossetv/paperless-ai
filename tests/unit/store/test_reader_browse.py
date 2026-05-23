"""Tests for store.reader._browse — the Library document-browse query.

list_documents lists documents from the index with pagination, sorting and
filtering, returning a DocumentPage (the page rows plus the total match
count).  The ``populated_db`` fixture and the ``unit_vec`` helper come from
tests/unit/store/conftest.py.

Coverage:
- sorting by created / title / indexed_at, ascending and descending
- an unknown sort column raises ValueError
- pagination slices the result and total is the unpaginated count
- filtering by correspondent / document type / tags / date range
- the optional text query matches title, correspondent and type names
- page_count and resolved taxonomy names are present on each summary
- an empty index yields an empty page with total 0
- a corrupted tag_ids column falls back to an empty tag list (no 500)
"""

from __future__ import annotations

import sqlite3

import pytest

from store.models import DocumentBrowseQuery, DocumentPage, DocumentSummary
from tests.helpers.store import open_reader, open_writer


def _query(**overrides: object) -> DocumentBrowseQuery:
    """Build a DocumentBrowseQuery with all-default (no-restriction) fields."""
    base: dict[str, object] = {
        "text": None,
        "date_from": None,
        "date_to": None,
        "correspondent_id": None,
        "document_type_id": None,
        "tag_ids": (),
        "sort": "created",
        "descending": True,
        "offset": 0,
        "limit": 20,
    }
    base.update(overrides)
    return DocumentBrowseQuery(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Shape and basic listing
# ---------------------------------------------------------------------------


def test_list_documents_returns_a_document_page(populated_db: str) -> None:
    """list_documents returns a DocumentPage of DocumentSummary rows."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query())
    reader.close()
    assert isinstance(page, DocumentPage)
    assert page.total == 2
    assert page.offset == 0
    assert page.limit == 20
    assert all(isinstance(d, DocumentSummary) for d in page.documents)


def test_summary_carries_resolved_names_and_page_count(
    populated_db: str,
) -> None:
    """Each summary resolves taxonomy names and carries page_count and tags."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(sort="title", descending=False))
    reader.close()
    alpha = page.documents[0]
    assert alpha.id == 1
    assert alpha.title == "Alpha Invoice"
    assert alpha.correspondent == "Alpha Corp"
    assert alpha.document_type == "Invoice"
    assert alpha.page_count == 1
    assert set(alpha.tags) == {"important", "scanned"}


def test_summary_handles_null_document_type(populated_db: str) -> None:
    """A document with no document_type resolves it to None, not an error."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(sort="title", descending=False))
    reader.close()
    beta = page.documents[1]
    assert beta.id == 2
    assert beta.document_type is None
    assert beta.correspondent == "Beta Ltd"


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def test_sort_by_created_descending(populated_db: str) -> None:
    """Descending created sort puts the newer document first."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(sort="created", descending=True))
    reader.close()
    assert [d.id for d in page.documents] == [2, 1]


def test_sort_by_created_ascending(populated_db: str) -> None:
    """Ascending created sort puts the older document first."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(sort="created", descending=False))
    reader.close()
    assert [d.id for d in page.documents] == [1, 2]


def test_sort_by_title_ascending(populated_db: str) -> None:
    """Ascending title sort orders alphabetically (Alpha before Beta)."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(sort="title", descending=False))
    reader.close()
    assert [d.title for d in page.documents] == ["Alpha Invoice", "Beta Scan"]


def test_sort_by_indexed_at_is_accepted(populated_db: str) -> None:
    """indexed_at (date added) is a valid sort column and returns all rows."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(sort="indexed_at", descending=True))
    reader.close()
    assert page.total == 2
    assert len(page.documents) == 2


def test_unknown_sort_column_raises_value_error(populated_db: str) -> None:
    """An unsupported sort column is a programming error → ValueError."""
    reader = open_reader(populated_db)
    try:
        with pytest.raises(ValueError, match="sort"):
            reader.list_documents(_query(sort="content"))
    finally:
        reader.close()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_limit_slices_the_result(populated_db: str) -> None:
    """A limit of 1 returns one row but total still counts every match."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(sort="created", descending=False, limit=1))
    reader.close()
    assert len(page.documents) == 1
    assert page.documents[0].id == 1
    assert page.total == 2


def test_offset_skips_rows(populated_db: str) -> None:
    """An offset of 1 skips the first sorted row."""
    reader = open_reader(populated_db)
    page = reader.list_documents(
        _query(sort="created", descending=False, offset=1, limit=1)
    )
    reader.close()
    assert len(page.documents) == 1
    assert page.documents[0].id == 2
    assert page.total == 2
    assert page.offset == 1


def test_offset_past_the_end_yields_empty_documents(
    populated_db: str,
) -> None:
    """An offset beyond the result still reports the real total."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(offset=100, limit=20))
    reader.close()
    assert page.documents == ()
    assert page.total == 2


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_filter_by_correspondent(populated_db: str) -> None:
    """A correspondent filter restricts the page and the total."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(correspondent_id=10))
    reader.close()
    assert page.total == 1
    assert page.documents[0].id == 1


def test_filter_by_document_type(populated_db: str) -> None:
    """A document-type filter restricts the page and the total."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(document_type_id=20))
    reader.close()
    assert page.total == 1
    assert page.documents[0].id == 1


def test_filter_by_tag(populated_db: str) -> None:
    """Tag 101 belongs only to document 1, so the filter isolates it."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(tag_ids=(101,)))
    reader.close()
    assert page.total == 1
    assert page.documents[0].id == 1


def test_filter_by_tag_shared_by_both(populated_db: str) -> None:
    """Tag 102 belongs to both documents, so the filter keeps both."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(tag_ids=(102,)))
    reader.close()
    assert page.total == 2


def test_filter_by_date_range(populated_db: str) -> None:
    """A 2024 date range keeps only the 2024 document."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(date_from="2024-01-01", date_to="2024-12-31"))
    reader.close()
    assert page.total == 1
    assert page.documents[0].id == 2


def test_text_query_matches_title(populated_db: str) -> None:
    """A text query matching a title returns only that document."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(text="alpha"))
    reader.close()
    assert page.total == 1
    assert page.documents[0].id == 1


def test_text_query_matches_correspondent_name(populated_db: str) -> None:
    """A text query matching a correspondent name returns that document."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(text="beta ltd"))
    reader.close()
    assert page.total == 1
    assert page.documents[0].id == 2


def test_text_query_is_case_insensitive(populated_db: str) -> None:
    """The text query matches regardless of letter case."""
    reader = open_reader(populated_db)
    page = reader.list_documents(_query(text="INVOICE"))
    reader.close()
    # "Invoice" appears in document 1's title and as its document type.
    assert page.total == 1
    assert page.documents[0].id == 1


def test_filters_and_text_combine(populated_db: str) -> None:
    """A text query and a correspondent filter are ANDed together."""
    reader = open_reader(populated_db)
    # text "scan" matches document 2's title; correspondent 10 is document 1.
    page = reader.list_documents(_query(text="scan", correspondent_id=10))
    reader.close()
    assert page.total == 0
    assert page.documents == ()


# ---------------------------------------------------------------------------
# Empty index
# ---------------------------------------------------------------------------


def test_empty_index_yields_empty_page(db_path: str) -> None:
    """An index with no documents returns an empty page with total 0."""
    writer = open_writer(db_path)
    writer.close()  # schema created, no documents written
    reader = open_reader(db_path)
    page = reader.list_documents(_query())
    reader.close()
    assert page.documents == ()
    assert page.total == 0


# ---------------------------------------------------------------------------
# Fault tolerance
# ---------------------------------------------------------------------------


def test_corrupted_tag_ids_falls_back_to_empty_tags(populated_db: str) -> None:
    """A corrupted tag_ids column does not raise — it falls back to no tags.

    Defence-in-depth: if a hand-edited DB stores a non-JSON value in
    tag_ids, the browse query must not 500.  The document is returned with an
    empty tag list and a structured warning is emitted (not tested here — the
    behaviour under test is that no exception is raised and the document is
    still present in the page).
    """
    conn = sqlite3.connect(populated_db)
    try:
        conn.execute("UPDATE documents SET tag_ids = 'not-json' WHERE id = 1")
        conn.commit()
    finally:
        conn.close()

    reader = open_reader(populated_db)
    try:
        page = reader.list_documents(_query())
    finally:
        reader.close()

    assert page.total == 2
    corrupted_doc = next(d for d in page.documents if d.id == 1)
    assert corrupted_doc.tags == ()  # graceful fallback — no 500
