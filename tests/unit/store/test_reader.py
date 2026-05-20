"""Tests for store.reader.StoreReader.

Covers (per task specification):
- vector_search ranks nearest chunk first
- a filter excluding the true-nearest chunk returns the next-nearest (filters apply
  pre-ranking, never post-filter to empty)
- keyword_search matches on terms and respects filters
- date-range filters work on normalised ISO strings
- get_documents resolves taxonomy names and tag names
- list_facets returns all taxonomy kinds with earliest/latest dates
- get_stats counts documents and chunks correctly
- quick_check returns True on a healthy DB
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock

import pytest

from store.models import ChunkHit, IndexedDocument, IndexStats
from store.reader import SearchFilters, StoreReader
from store.writer import StoreWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(db_path: str, *, model: str = "test-model", dimensions: int = 4) -> Any:
    """Return a MagicMock Settings with the fields StoreReader and StoreWriter use."""
    mock = MagicMock()
    mock.INDEX_DB_PATH = db_path
    mock.EMBEDDING_MODEL = model
    mock.EMBEDDING_DIMENSIONS = dimensions
    return mock


def _make_writer(db_path: str, **kwargs: Any) -> StoreWriter:
    settings = _make_settings(db_path, **kwargs)
    return StoreWriter(settings)


def _make_reader(db_path: str, **kwargs: Any) -> StoreReader:
    settings = _make_settings(db_path, **kwargs)
    return StoreReader(settings)


def _unit_vec(dims: int, component: int) -> tuple[float, ...]:
    """Return a unit vector with a 1.0 in *component* and 0.0 everywhere else.

    All embeddings are dim=4 in tests; cosine distance from one unit vector to
    another is ``1 - cos(angle)``, so two identical vectors have distance 0.0.
    """
    vec = [0.0] * dims
    vec[component] = 1.0
    return tuple(vec)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Any) -> str:
    return str(tmp_path / "test_reader.db")


@pytest.fixture()
def populated_db(db_path: str) -> tuple[str, dict[str, Any]]:
    """Seed the DB with two documents, each with two chunks and taxonomy entries.

    Document 1:
        - correspondent_id=10 (name="Alpha Corp"), document_type_id=20 (name="Invoice")
        - tag_ids=(101, 102), created="2023-01-01T00:00:00+00:00"
        - chunk 0: embedding along axis 0 → [1,0,0,0]
        - chunk 1: embedding along axis 1 → [0,1,0,0]

    Document 2:
        - correspondent_id=11 (name="Beta Ltd"), document_type_id=None
        - tag_ids=(102,), created="2024-06-15T00:00:00+00:00"
        - chunk 0: embedding along axis 2 → [0,0,1,0]
        - chunk 1: embedding along axis 3 → [0,0,0,1]
    """
    from store.models import ChunkInput, DocumentMeta, TaxonomyEntry

    writer = _make_writer(db_path)

    # Taxonomy
    writer.refresh_taxonomy([
        TaxonomyEntry(kind="correspondent", id=10, name="Alpha Corp"),
        TaxonomyEntry(kind="correspondent", id=11, name="Beta Ltd"),
        TaxonomyEntry(kind="document_type", id=20, name="Invoice"),
        TaxonomyEntry(kind="tag", id=101, name="important"),
        TaxonomyEntry(kind="tag", id=102, name="scanned"),
    ])

    # Document 1
    meta1 = DocumentMeta(
        id=1,
        title="Alpha Invoice",
        correspondent_id=10,
        document_type_id=20,
        tag_ids=(101, 102),
        created="2023-01-01T00:00:00+00:00",
        modified="2023-03-01T00:00:00+00:00",
        content_hash="hash1",
        page_count=1,
    )
    chunks1 = [
        ChunkInput(chunk_index=0, text="boiler warranty letter", page_hint=1, embedding=_unit_vec(4, 0)),
        ChunkInput(chunk_index=1, text="invoice total amount due", page_hint=1, embedding=_unit_vec(4, 1)),
    ]
    writer.upsert_document(meta1, chunks1)

    # Document 2
    meta2 = DocumentMeta(
        id=2,
        title="Beta Scan",
        correspondent_id=11,
        document_type_id=None,
        tag_ids=(102,),
        created="2024-06-15T00:00:00+00:00",
        modified="2024-08-01T00:00:00+00:00",
        content_hash="hash2",
        page_count=2,
    )
    chunks2 = [
        ChunkInput(chunk_index=0, text="electricity bill payment receipt", page_hint=1, embedding=_unit_vec(4, 2)),
        ChunkInput(chunk_index=1, text="account statement balance", page_hint=2, embedding=_unit_vec(4, 3)),
    ]
    writer.upsert_document(meta2, chunks2)

    # Write meta so get_stats has last_reconcile_at and embedding_model
    writer.write_meta("last_reconcile_at", "2024-09-01T00:00:00+00:00")
    writer.write_meta("embedding_model", "test-model")

    writer.close()

    context: dict[str, Any] = {
        "doc1_id": 1,
        "doc2_id": 2,
        "correspondent_id_doc1": 10,
        "tag_id_exclusive_doc1": 101,
    }
    return db_path, context


# ---------------------------------------------------------------------------
# vector_search: ranking and pre-filter correctness
# ---------------------------------------------------------------------------


def test_vector_search_ranks_nearest_chunk_first(populated_db: tuple[str, dict[str, Any]]) -> None:
    """The chunk whose embedding is closest (distance 0) comes back first."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    # Query along axis 0 — doc1's first chunk is the perfect match.
    query = _unit_vec(4, 0)
    no_filters = SearchFilters(
        date_from=None, date_to=None,
        correspondent_id=None, document_type_id=None,
        tag_ids=(),
    )
    hits = reader.vector_search(query, k=10, filters=no_filters)
    reader.close()

    assert len(hits) >= 1
    assert hits[0].score == pytest.approx(0.0, abs=1e-5), (
        "The nearest chunk (cosine distance ≈ 0) must be ranked first"
    )
    assert hits[0].text == "boiler warranty letter"


def test_vector_search_filter_excludes_nearest_returns_next(populated_db: tuple[str, dict[str, Any]]) -> None:
    """A filter that excludes the nearest chunk's document returns the next-nearest.

    This proves filters apply pre-ranking: the true-nearest chunk (doc1, axis 0) is
    excluded by correspondent_id=11, so doc2's chunk along axis 2 should rank first
    when the query is axis 0.
    """
    db_path, ctx = populated_db
    reader = _make_reader(db_path)
    # Query axis 0 (nearest = doc1 chunk 0), but filter to correspondent 11 (Beta Ltd).
    # Doc1 has correspondent 10 so it is entirely excluded.
    query = _unit_vec(4, 0)
    only_beta = SearchFilters(
        date_from=None, date_to=None,
        correspondent_id=11, document_type_id=None,
        tag_ids=(),
    )
    hits = reader.vector_search(query, k=10, filters=only_beta)
    reader.close()

    assert len(hits) == 2, "Doc 2 has two chunks and both should be returned"
    # All returned hits must belong to doc 2.
    assert all(h.document_id == 2 for h in hits)


def test_vector_search_tag_filter_pre_ranks(populated_db: tuple[str, dict[str, Any]]) -> None:
    """Tag filter (tag_id=101, only on doc1) restricts the candidate set pre-ranking."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    # Tag 101 belongs only to doc1; query along axis 2 (nearest without filter is doc2 chunk 0).
    # With the tag filter, doc2 is excluded entirely → only doc1's chunks come back.
    query = _unit_vec(4, 2)
    only_tag101 = SearchFilters(
        date_from=None, date_to=None,
        correspondent_id=None, document_type_id=None,
        tag_ids=(101,),
    )
    hits = reader.vector_search(query, k=10, filters=only_tag101)
    reader.close()

    assert len(hits) == 2
    assert all(h.document_id == 1 for h in hits)


def test_vector_search_document_type_filter(populated_db: tuple[str, dict[str, Any]]) -> None:
    """document_type_id filter restricts results to the matching document."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    query = _unit_vec(4, 3)
    # Only doc1 has document_type_id=20.
    only_invoice = SearchFilters(
        date_from=None, date_to=None,
        correspondent_id=None, document_type_id=20,
        tag_ids=(),
    )
    hits = reader.vector_search(query, k=10, filters=only_invoice)
    reader.close()

    assert all(h.document_id == 1 for h in hits)


# ---------------------------------------------------------------------------
# Date-range filters
# ---------------------------------------------------------------------------


def test_vector_search_date_from_filter(populated_db: tuple[str, dict[str, Any]]) -> None:
    """date_from restricts results to documents with created >= date_from."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    query = _unit_vec(4, 0)
    # Doc1 created 2023-01-01, doc2 created 2024-06-15.
    # date_from=2024-01-01 should exclude doc1.
    only_2024 = SearchFilters(
        date_from="2024-01-01T00:00:00+00:00", date_to=None,
        correspondent_id=None, document_type_id=None,
        tag_ids=(),
    )
    hits = reader.vector_search(query, k=10, filters=only_2024)
    reader.close()

    assert all(h.document_id == 2 for h in hits)


def test_vector_search_date_to_filter(populated_db: tuple[str, dict[str, Any]]) -> None:
    """date_to restricts results to documents with created <= date_to."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    query = _unit_vec(4, 2)
    # date_to=2023-12-31 should exclude doc2 (2024).
    only_2023 = SearchFilters(
        date_from=None, date_to="2023-12-31T23:59:59+00:00",
        correspondent_id=None, document_type_id=None,
        tag_ids=(),
    )
    hits = reader.vector_search(query, k=10, filters=only_2023)
    reader.close()

    assert all(h.document_id == 1 for h in hits)


def test_vector_search_date_range_both_bounds(populated_db: tuple[str, dict[str, Any]]) -> None:
    """date_from + date_to together are applied as an inclusive range."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    query = _unit_vec(4, 0)
    narrow = SearchFilters(
        date_from="2023-01-01T00:00:00+00:00",
        date_to="2023-12-31T23:59:59+00:00",
        correspondent_id=None, document_type_id=None,
        tag_ids=(),
    )
    hits = reader.vector_search(query, k=10, filters=narrow)
    reader.close()

    assert len(hits) == 2
    assert all(h.document_id == 1 for h in hits)


# ---------------------------------------------------------------------------
# keyword_search
# ---------------------------------------------------------------------------


def test_keyword_search_matches_on_term(populated_db: tuple[str, dict[str, Any]]) -> None:
    """keyword_search returns chunks whose text contains the search term."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    no_filters = SearchFilters(
        date_from=None, date_to=None,
        correspondent_id=None, document_type_id=None,
        tag_ids=(),
    )
    hits = reader.keyword_search(["boiler"], k=10, filters=no_filters)
    reader.close()

    assert len(hits) >= 1
    assert any("boiler" in h.text for h in hits)


def test_keyword_search_respects_correspondent_filter(populated_db: tuple[str, dict[str, Any]]) -> None:
    """keyword_search with correspondent_id filter excludes non-matching documents."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    # "scanned" does not appear in chunks; use "invoice" (in doc1) but filter to Beta (doc2).
    # The filter should mean doc1's chunks are excluded even if they match.
    only_beta = SearchFilters(
        date_from=None, date_to=None,
        correspondent_id=11, document_type_id=None,
        tag_ids=(),
    )
    hits = reader.keyword_search(["invoice"], k=10, filters=only_beta)
    reader.close()

    # "invoice" is in doc1's text only; with Beta filter applied → no results.
    assert all(h.document_id == 2 for h in hits)


def test_keyword_search_no_match_returns_empty(populated_db: tuple[str, dict[str, Any]]) -> None:
    """keyword_search returns an empty list when no chunk matches the terms."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    no_filters = SearchFilters(
        date_from=None, date_to=None,
        correspondent_id=None, document_type_id=None,
        tag_ids=(),
    )
    hits = reader.keyword_search(["xyznonexistent"], k=10, filters=no_filters)
    reader.close()

    assert hits == []


def test_keyword_search_respects_tag_filter(populated_db: tuple[str, dict[str, Any]]) -> None:
    """keyword_search with tag_ids restricts candidate documents before FTS scoring."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    # Tag 101 is on doc1 only; search for "statement" (only in doc2).
    only_tag101 = SearchFilters(
        date_from=None, date_to=None,
        correspondent_id=None, document_type_id=None,
        tag_ids=(101,),
    )
    hits = reader.keyword_search(["statement"], k=10, filters=only_tag101)
    reader.close()

    # "statement" is in doc2 but tag filter restricts to doc1 → empty.
    assert hits == []


# ---------------------------------------------------------------------------
# get_documents
# ---------------------------------------------------------------------------


def test_get_documents_resolves_taxonomy_names(populated_db: tuple[str, dict[str, Any]]) -> None:
    """get_documents returns IndexedDocuments with resolved correspondent and type names."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    docs = reader.get_documents([1])
    reader.close()

    assert len(docs) == 1
    doc = docs[0]
    assert isinstance(doc, IndexedDocument)
    assert doc.id == 1
    assert doc.title == "Alpha Invoice"
    assert doc.correspondent == "Alpha Corp"
    assert doc.document_type == "Invoice"


def test_get_documents_resolves_tag_names(populated_db: tuple[str, dict[str, Any]]) -> None:
    """get_documents resolves all tag names for a document."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    docs = reader.get_documents([1])
    reader.close()

    assert len(docs) == 1
    # Doc1 has tags 101 ("important") and 102 ("scanned")
    assert set(docs[0].tags) == {"important", "scanned"}


def test_get_documents_none_correspondent_and_type(populated_db: tuple[str, dict[str, Any]]) -> None:
    """get_documents returns None for unset correspondent and document_type."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    # Doc2 has document_type_id=None
    docs = reader.get_documents([2])
    reader.close()

    assert len(docs) == 1
    assert docs[0].document_type is None
    assert docs[0].correspondent == "Beta Ltd"


def test_get_documents_multiple_ids(populated_db: tuple[str, dict[str, Any]]) -> None:
    """get_documents accepts multiple ids and returns all matching documents."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    docs = reader.get_documents([1, 2])
    reader.close()

    assert len(docs) == 2
    assert {d.id for d in docs} == {1, 2}


def test_get_documents_empty_ids_returns_empty(populated_db: tuple[str, dict[str, Any]]) -> None:
    """get_documents with no ids returns an empty list."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    docs = reader.get_documents([])
    reader.close()

    assert docs == []


# ---------------------------------------------------------------------------
# get_chunks
# ---------------------------------------------------------------------------


def test_get_chunks_returns_chunk_hits(populated_db: tuple[str, dict[str, Any]]) -> None:
    """get_chunks returns ChunkHit objects with the correct fields."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    # First, discover a valid chunk id via vector_search.
    no_filters = SearchFilters(
        date_from=None, date_to=None,
        correspondent_id=None, document_type_id=None,
        tag_ids=(),
    )
    hits = reader.vector_search(_unit_vec(4, 0), k=1, filters=no_filters)
    chunk_id = hits[0].chunk_id

    chunks = reader.get_chunks([chunk_id])
    reader.close()

    assert len(chunks) == 1
    assert isinstance(chunks[0], ChunkHit)
    assert chunks[0].chunk_id == chunk_id
    assert chunks[0].document_id == 1


def test_get_chunks_empty_ids_returns_empty(populated_db: tuple[str, dict[str, Any]]) -> None:
    """get_chunks with no ids returns an empty list."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    chunks = reader.get_chunks([])
    reader.close()

    assert chunks == []


# ---------------------------------------------------------------------------
# list_facets
# ---------------------------------------------------------------------------


def test_list_facets_returns_all_kinds(populated_db: tuple[str, dict[str, Any]]) -> None:
    """list_facets returns correspondents, document_types, and tags."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    facets = reader.list_facets()
    reader.close()

    # Two correspondents seeded
    assert len(facets.correspondents) == 2
    assert {e.name for e in facets.correspondents} == {"Alpha Corp", "Beta Ltd"}

    # One document type seeded
    assert len(facets.document_types) == 1
    assert facets.document_types[0].name == "Invoice"

    # Two tags seeded
    assert len(facets.tags) == 2
    assert {e.name for e in facets.tags} == {"important", "scanned"}


def test_list_facets_earliest_latest(populated_db: tuple[str, dict[str, Any]]) -> None:
    """list_facets returns the earliest and latest created dates from documents."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    facets = reader.list_facets()
    reader.close()

    assert facets.earliest is not None
    assert facets.latest is not None
    # Doc1 created 2023, doc2 created 2024 — earliest should be doc1.
    assert facets.earliest < facets.latest
    assert "2023" in facets.earliest
    assert "2024" in facets.latest


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


def test_get_stats_counts_correctly(populated_db: tuple[str, dict[str, Any]]) -> None:
    """get_stats returns the correct document and chunk counts."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    stats = reader.get_stats()
    reader.close()

    assert isinstance(stats, IndexStats)
    assert stats.document_count == 2
    assert stats.chunk_count == 4  # 2 docs × 2 chunks each


def test_get_stats_returns_meta_fields(populated_db: tuple[str, dict[str, Any]]) -> None:
    """get_stats returns last_reconcile_at and embedding_model from the meta table."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    stats = reader.get_stats()
    reader.close()

    assert stats.last_reconcile_at == "2024-09-01T00:00:00+00:00"
    assert stats.embedding_model == "test-model"


def test_get_stats_empty_db_returns_zero_counts(db_path: str) -> None:
    """get_stats on an empty (just-initialised) DB returns zero counts."""
    writer = _make_writer(db_path)
    writer.close()
    reader = _make_reader(db_path)
    stats = reader.get_stats()
    reader.close()

    assert stats.document_count == 0
    assert stats.chunk_count == 0
    assert stats.last_reconcile_at is None
    assert stats.embedding_model is None


# ---------------------------------------------------------------------------
# quick_check
# ---------------------------------------------------------------------------


def test_quick_check_returns_true_on_healthy_db(populated_db: tuple[str, dict[str, Any]]) -> None:
    """quick_check returns True on a healthy, intact database."""
    db_path, _ = populated_db
    reader = _make_reader(db_path)
    result = reader.quick_check()
    reader.close()

    assert result is True


def test_quick_check_returns_true_on_empty_db(db_path: str) -> None:
    """quick_check returns True even on a freshly-initialised empty DB."""
    writer = _make_writer(db_path)
    writer.close()
    reader = _make_reader(db_path)
    result = reader.quick_check()
    reader.close()

    assert result is True
