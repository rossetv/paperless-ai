"""Tests for StoreReader.keyword_document_search — FTS grouped to documents.

Covers:
- a content keyword matches and is grouped to one row per document, with a
  best-chunk snippet;
- the same pre-ranking SearchFilters that ranked retrieval uses apply here too;
- pagination returns disjoint pages and a stable total;
- the empty-terms / non-positive-limit guards return an empty page.

The ``populated_db`` fixture and ``unit_vec`` helper come from
tests/unit/store/conftest.py; ``open_writer``/``open_reader`` from
tests/helpers/store.py.
"""

from __future__ import annotations

from store.models import ChunkInput, DocumentMeta, TaxonomyEntry
from tests.helpers.factories import make_search_filters
from tests.helpers.store import open_reader, open_writer
from tests.unit.store.conftest import unit_vec


def test_keyword_document_search_matches_content_and_groups_by_document(
    populated_db: str,
) -> None:
    """A content term matches its document once, with a snippet from the hit."""
    reader = open_reader(populated_db)
    page = reader.keyword_document_search(
        ["invoice"], make_search_filters(), limit=10, offset=0
    )
    reader.close()

    # Only document 1 has "invoice" in a chunk ("invoice total amount due").
    assert page.total == 1
    assert len(page.hits) == 1
    assert page.hits[0].document.id == 1
    assert page.hits[0].document.title == "Alpha Invoice"
    assert "invoice" in (page.hits[0].snippet or "").lower()


def test_keyword_document_search_applies_filters(populated_db: str) -> None:
    """A correspondent filter excluding the match returns nothing."""
    reader = open_reader(populated_db)
    # "invoice" lives in document 1 (correspondent 10); filter to 11 → no match.
    page = reader.keyword_document_search(
        ["invoice"], make_search_filters(correspondent_id=11), limit=10, offset=0
    )
    reader.close()

    assert page.total == 0
    assert page.hits == ()


def test_keyword_document_search_paginates(db_path: str) -> None:
    """Two documents sharing a term paginate into disjoint single-doc pages."""
    writer = open_writer(db_path)
    writer.refresh_taxonomy([TaxonomyEntry(kind="correspondent", id=10, name="Acme")])
    for doc_id in (1, 2):
        writer.upsert_document(
            DocumentMeta(
                id=doc_id,
                title=f"Report {doc_id}",
                correspondent_id=10,
                document_type_id=None,
                tag_ids=(),
                created="2024-01-01T00:00:00+00:00",
                modified="2024-01-02T00:00:00+00:00",
                content_hash=f"hash{doc_id}",
                page_count=1,
            ),
            [
                ChunkInput(
                    chunk_index=0,
                    text=f"annual report number {doc_id}",
                    page_hint=1,
                    embedding=unit_vec(4, doc_id % 4),
                )
            ],
        )
    writer.close()

    reader = open_reader(db_path)
    page1 = reader.keyword_document_search(
        ["report"], make_search_filters(), limit=1, offset=0
    )
    page2 = reader.keyword_document_search(
        ["report"], make_search_filters(), limit=1, offset=1
    )
    reader.close()

    assert page1.total == 2 and page2.total == 2
    assert len(page1.hits) == 1 and len(page2.hits) == 1
    assert page1.hits[0].document.id != page2.hits[0].document.id


def test_keyword_document_search_empty_terms_returns_empty(populated_db: str) -> None:
    """No terms (and a non-positive limit) short-circuit to an empty page."""
    reader = open_reader(populated_db)
    empty = reader.keyword_document_search(
        [], make_search_filters(), limit=10, offset=0
    )
    zero_limit = reader.keyword_document_search(
        ["invoice"], make_search_filters(), limit=0, offset=0
    )
    reader.close()

    assert empty.total == 0 and empty.hits == ()
    assert zero_limit.total == 0 and zero_limit.hits == ()
