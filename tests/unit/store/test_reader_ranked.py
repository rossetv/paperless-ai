"""Tests for store.reader._ranked — vector and keyword ranked retrieval.

Covers:
- vector_search ranks the nearest chunk first
- a filter excluding the true-nearest chunk returns the next-nearest (filters
  apply pre-ranking, never post-filter to empty)
- keyword_search matches on terms and respects filters
- date-range filters work on normalised ISO strings
- the k<=0 guards return [] without touching the database

The look-up and introspection behaviours live in test_reader_lookups.py — the
reader's tests mirror the store/reader/ package split (CODE_GUIDELINES §11.2).
The ``db_path``, ``populated_db`` fixtures and the ``unit_vec`` helper come
from tests/unit/store/conftest.py.
"""

from __future__ import annotations

import pytest

from tests.helpers.factories import make_search_filters
from tests.helpers.store import open_reader, open_writer
from tests.unit.store.conftest import unit_vec


# ---------------------------------------------------------------------------
# vector_search: ranking and pre-filter correctness
# ---------------------------------------------------------------------------


def test_vector_search_ranks_nearest_chunk_first(populated_db: str) -> None:
    """The chunk whose embedding is closest (distance 0) comes back first."""
    reader = open_reader(populated_db)
    # Query along axis 0 — doc1's first chunk is the perfect match.
    hits = reader.vector_search(unit_vec(4, 0), k=10, filters=make_search_filters())
    reader.close()

    assert len(hits) >= 1
    assert hits[0].score == pytest.approx(0.0, abs=1e-5), (
        "The nearest chunk (cosine distance ≈ 0) must be ranked first"
    )
    assert hits[0].text == "boiler warranty letter"


def test_vector_search_filter_excludes_nearest_returns_next(
    populated_db: str,
) -> None:
    """A filter that excludes the nearest chunk's document returns the next-nearest.

    This proves filters apply pre-ranking: the true-nearest chunk (doc1, axis 0)
    is excluded by correspondent_id=11, so doc2's chunks are all that remain
    even when the query is axis 0.
    """
    reader = open_reader(populated_db)
    # Query axis 0 (nearest = doc1 chunk 0), filtered to correspondent 11
    # (Beta Ltd).  Doc1 has correspondent 10 so it is entirely excluded.
    hits = reader.vector_search(
        unit_vec(4, 0), k=10, filters=make_search_filters(correspondent_id=11)
    )
    reader.close()

    assert len(hits) == 2, "Doc 2 has two chunks and both should be returned"
    assert all(hit.document_id == 2 for hit in hits)


def test_vector_search_tag_filter_pre_ranks(populated_db: str) -> None:
    """Tag filter (tag_id=101, only on doc1) restricts the candidate set pre-ranking."""
    reader = open_reader(populated_db)
    # Tag 101 belongs only to doc1; query along axis 2 (nearest without a filter
    # is doc2 chunk 0).  With the tag filter doc2 is excluded entirely.
    hits = reader.vector_search(
        unit_vec(4, 2), k=10, filters=make_search_filters(tag_ids=(101,))
    )
    reader.close()

    assert len(hits) == 2
    assert all(hit.document_id == 1 for hit in hits)


def test_vector_search_document_type_filter(populated_db: str) -> None:
    """document_type_id filter restricts results to the matching document."""
    reader = open_reader(populated_db)
    # Only doc1 has document_type_id=20.
    hits = reader.vector_search(
        unit_vec(4, 3), k=10, filters=make_search_filters(document_type_id=20)
    )
    reader.close()

    assert all(hit.document_id == 1 for hit in hits)


# ---------------------------------------------------------------------------
# Date-range filters
# ---------------------------------------------------------------------------


def test_vector_search_date_from_filter(populated_db: str) -> None:
    """date_from restricts results to documents with created >= date_from."""
    reader = open_reader(populated_db)
    # Doc1 created 2023-01-01, doc2 created 2024-06-15.
    # date_from=2024-01-01 should exclude doc1.
    hits = reader.vector_search(
        unit_vec(4, 0),
        k=10,
        filters=make_search_filters(date_from="2024-01-01T00:00:00+00:00"),
    )
    reader.close()

    assert all(hit.document_id == 2 for hit in hits)


def test_vector_search_date_to_filter(populated_db: str) -> None:
    """date_to restricts results to documents with created <= date_to."""
    reader = open_reader(populated_db)
    # date_to=2023-12-31 should exclude doc2 (2024).
    hits = reader.vector_search(
        unit_vec(4, 2),
        k=10,
        filters=make_search_filters(date_to="2023-12-31T23:59:59+00:00"),
    )
    reader.close()

    assert all(hit.document_id == 1 for hit in hits)


def test_vector_search_date_range_both_bounds(populated_db: str) -> None:
    """date_from + date_to together are applied as an inclusive range."""
    reader = open_reader(populated_db)
    hits = reader.vector_search(
        unit_vec(4, 0),
        k=10,
        filters=make_search_filters(
            date_from="2023-01-01",
            date_to="2023-12-31",
        ),
    )
    reader.close()

    assert len(hits) == 2
    assert all(hit.document_id == 1 for hit in hits)


# ---------------------------------------------------------------------------
# keyword_search
# ---------------------------------------------------------------------------


def test_keyword_search_matches_on_term(populated_db: str) -> None:
    """keyword_search returns chunks whose text contains the search term."""
    reader = open_reader(populated_db)
    hits = reader.keyword_search(["boiler"], k=10, filters=make_search_filters())
    reader.close()

    assert len(hits) >= 1
    assert any("boiler" in hit.text for hit in hits)


def test_keyword_search_respects_correspondent_filter(populated_db: str) -> None:
    """keyword_search with a correspondent_id filter excludes non-matching documents."""
    reader = open_reader(populated_db)
    # "invoice" is in doc1's text only; filtering to Beta (doc2) must drop it.
    hits = reader.keyword_search(
        ["invoice"], k=10, filters=make_search_filters(correspondent_id=11)
    )
    reader.close()

    assert all(hit.document_id == 2 for hit in hits)


def test_keyword_search_no_match_returns_empty(populated_db: str) -> None:
    """keyword_search returns an empty list when no chunk matches the terms."""
    reader = open_reader(populated_db)
    hits = reader.keyword_search(
        ["xyznonexistent"], k=10, filters=make_search_filters()
    )
    reader.close()

    assert hits == []


def test_keyword_search_respects_tag_filter(populated_db: str) -> None:
    """keyword_search with tag_ids restricts candidate documents before FTS scoring."""
    reader = open_reader(populated_db)
    # Tag 101 is on doc1 only; "statement" is in doc2 — the filter drops doc2.
    hits = reader.keyword_search(
        ["statement"], k=10, filters=make_search_filters(tag_ids=(101,))
    )
    reader.close()

    assert hits == []


def test_keyword_search_respects_date_range_filter(db_path: str) -> None:
    """keyword_search with date_from/date_to returns only in-range matches.

    Seeded documents share a common term ("quarterly") but differ in their
    created date; the date-range filter must exclude out-of-range documents
    before FTS scoring, not post-filter the ranked results.
    """
    from store.models import ChunkInput, DocumentMeta

    writer = open_writer(db_path)
    common_chunk = ChunkInput(
        chunk_index=0,
        text="quarterly earnings report summary",
        page_hint=1,
        embedding=unit_vec(4, 0),
    )
    writer.upsert_document(
        DocumentMeta(
            id=10,
            title="Report 2022",
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(),
            created="2022-03-01T00:00:00+00:00",
            modified="2022-03-01T00:00:00+00:00",
            content_hash="c2022",
            page_count=1,
        ),
        [common_chunk],
    )
    writer.upsert_document(
        DocumentMeta(
            id=11,
            title="Report 2024",
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(),
            created="2024-09-15T00:00:00+00:00",
            modified="2024-09-15T00:00:00+00:00",
            content_hash="c2024",
            page_count=1,
        ),
        [common_chunk],
    )
    writer.close()

    reader = open_reader(db_path)
    all_hits = reader.keyword_search(["quarterly"], k=10, filters=make_search_filters())
    assert len(all_hits) == 2, "both docs match without a date filter"

    # Restrict to 2024 only — the 2022 document must be excluded.
    hits_2024 = reader.keyword_search(
        ["quarterly"],
        k=10,
        filters=make_search_filters(date_from="2024-01-01T00:00:00+00:00"),
    )
    assert len(hits_2024) == 1
    assert hits_2024[0].document_id == 11, "only the 2024 document should be returned"

    # Restrict to 2022 only — the 2024 document must be excluded.
    hits_2022 = reader.keyword_search(
        ["quarterly"],
        k=10,
        filters=make_search_filters(date_to="2022-12-31T23:59:59+00:00"),
    )
    reader.close()
    assert len(hits_2022) == 1
    assert hits_2022[0].document_id == 10, "only the 2022 document should be returned"


# ---------------------------------------------------------------------------
# k <= 0 guard — must not run a query nor return the whole table
# ---------------------------------------------------------------------------


def test_vector_search_k_zero_returns_empty(populated_db: str) -> None:
    """vector_search with k=0 must return [] without executing a query."""
    reader = open_reader(populated_db)
    hits = reader.vector_search(unit_vec(4, 0), k=0, filters=make_search_filters())
    reader.close()
    assert hits == []


def test_vector_search_k_negative_returns_empty(populated_db: str) -> None:
    """vector_search with k<0 must return [] rather than the whole table (the
    SQLite LIMIT -1 trap)."""
    reader = open_reader(populated_db)
    hits = reader.vector_search(unit_vec(4, 0), k=-1, filters=make_search_filters())
    reader.close()
    assert hits == []


def test_keyword_search_k_zero_returns_empty(populated_db: str) -> None:
    """keyword_search with k=0 must return []."""
    reader = open_reader(populated_db)
    hits = reader.keyword_search(["boiler"], k=0, filters=make_search_filters())
    reader.close()
    assert hits == []


def test_keyword_search_k_negative_returns_empty(populated_db: str) -> None:
    """keyword_search with k<0 must return [] rather than the whole table."""
    reader = open_reader(populated_db)
    hits = reader.keyword_search(["boiler"], k=-5, filters=make_search_filters())
    reader.close()
    assert hits == []
