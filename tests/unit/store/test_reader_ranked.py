"""Tests for store.reader._ranked, vector and keyword ranked retrieval.

Filters apply before ranking, so excluding the nearest chunk returns the
next-nearest rather than an empty result.
"""

from __future__ import annotations

import pytest

from tests.helpers.factories import make_search_filters
from tests.helpers.store import open_reader, open_writer
from tests.unit.store.conftest import unit_vec


def test_vector_search_ranks_nearest_chunk_first(populated_db: str) -> None:
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
    reader = open_reader(populated_db)
    # The axis-0 query's nearest chunk is doc1's, but doc1 is correspondent 10.
    hits = reader.vector_search(
        unit_vec(4, 0), k=10, filters=make_search_filters(correspondent_id=11)
    )
    reader.close()

    assert len(hits) == 2, "Doc 2 has two chunks and both should be returned"
    assert all(hit.document_id == 2 for hit in hits)


def test_vector_search_tag_filter_pre_ranks(populated_db: str) -> None:
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
    reader = open_reader(populated_db)
    # Only doc1 has document_type_id=20.
    hits = reader.vector_search(
        unit_vec(4, 3), k=10, filters=make_search_filters(document_type_id=20)
    )
    reader.close()

    assert all(hit.document_id == 1 for hit in hits)


def test_vector_search_date_from_filter(populated_db: str) -> None:
    reader = open_reader(populated_db)
    # Doc1 was created in 2023, doc2 in 2024.
    hits = reader.vector_search(
        unit_vec(4, 0),
        k=10,
        filters=make_search_filters(date_from="2024-01-01T00:00:00+00:00"),
    )
    reader.close()

    assert all(hit.document_id == 2 for hit in hits)


def test_vector_search_date_to_filter(populated_db: str) -> None:
    reader = open_reader(populated_db)
    hits = reader.vector_search(
        unit_vec(4, 2),
        k=10,
        filters=make_search_filters(date_to="2023-12-31T23:59:59+00:00"),
    )
    reader.close()

    assert all(hit.document_id == 1 for hit in hits)


def test_vector_search_date_range_both_bounds(populated_db: str) -> None:
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


def test_keyword_search_matches_on_term(populated_db: str) -> None:
    reader = open_reader(populated_db)
    hits = reader.keyword_search(["boiler"], k=10, filters=make_search_filters())
    reader.close()

    assert len(hits) >= 1
    assert any("boiler" in hit.text for hit in hits)


def test_keyword_search_respects_correspondent_filter(populated_db: str) -> None:
    reader = open_reader(populated_db)
    # "invoice" is in doc1's text only; filtering to Beta (doc2) must drop it.
    hits = reader.keyword_search(
        ["invoice"], k=10, filters=make_search_filters(correspondent_id=11)
    )
    reader.close()

    assert all(hit.document_id == 2 for hit in hits)


def test_keyword_search_no_match_returns_empty(populated_db: str) -> None:
    reader = open_reader(populated_db)
    hits = reader.keyword_search(
        ["xyznonexistent"], k=10, filters=make_search_filters()
    )
    reader.close()

    assert hits == []


def test_keyword_search_respects_tag_filter(populated_db: str) -> None:
    reader = open_reader(populated_db)
    # Tag 101 is on doc1 only; "statement" is in doc2 — the filter drops doc2.
    hits = reader.keyword_search(
        ["statement"], k=10, filters=make_search_filters(tag_ids=(101,))
    )
    reader.close()

    assert hits == []


def test_keyword_search_respects_date_range_filter(db_path: str) -> None:
    """Both documents share the term; only their created dates differ."""
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

    hits_2024 = reader.keyword_search(
        ["quarterly"],
        k=10,
        filters=make_search_filters(date_from="2024-01-01T00:00:00+00:00"),
    )
    assert len(hits_2024) == 1
    assert hits_2024[0].document_id == 11, "only the 2024 document should be returned"

    hits_2022 = reader.keyword_search(
        ["quarterly"],
        k=10,
        filters=make_search_filters(date_to="2022-12-31T23:59:59+00:00"),
    )
    reader.close()
    assert len(hits_2022) == 1
    assert hits_2022[0].document_id == 10, "only the 2022 document should be returned"


def test_vector_search_k_zero_returns_empty(populated_db: str) -> None:
    reader = open_reader(populated_db)
    hits = reader.vector_search(unit_vec(4, 0), k=0, filters=make_search_filters())
    reader.close()
    assert hits == []


def test_vector_search_k_negative_returns_empty(populated_db: str) -> None:
    """SQLite treats LIMIT -1 as no limit, so k<0 must not reach the query."""
    reader = open_reader(populated_db)
    hits = reader.vector_search(unit_vec(4, 0), k=-1, filters=make_search_filters())
    reader.close()
    assert hits == []


def test_keyword_search_k_zero_returns_empty(populated_db: str) -> None:
    reader = open_reader(populated_db)
    hits = reader.keyword_search(["boiler"], k=0, filters=make_search_filters())
    reader.close()
    assert hits == []


def test_keyword_search_k_negative_returns_empty(populated_db: str) -> None:
    reader = open_reader(populated_db)
    hits = reader.keyword_search(["boiler"], k=-5, filters=make_search_filters())
    reader.close()
    assert hits == []
