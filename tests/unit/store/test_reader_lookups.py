"""Tests for store.reader._lookups, the reader's look-ups and introspection."""

from __future__ import annotations

import pytest

from store import SchemaNotReadyError
from store.models import ChunkHit, IndexedDocument, IndexStats, TaxonomyEntry
from tests.helpers.factories import make_search_filters
from tests.helpers.store import open_reader, open_writer
from tests.unit.store.conftest import unit_vec


def test_get_documents_resolves_taxonomy_names(populated_db: str) -> None:
    reader = open_reader(populated_db)
    documents = reader.get_documents([1])
    reader.close()

    assert len(documents) == 1
    document = documents[0]
    assert isinstance(document, IndexedDocument)
    assert document.id == 1
    assert document.title == "Alpha Invoice"
    assert document.correspondent == "Alpha Corp"
    assert document.document_type == "Invoice"


def test_get_documents_resolves_tag_names(populated_db: str) -> None:
    reader = open_reader(populated_db)
    documents = reader.get_documents([1])
    reader.close()

    assert len(documents) == 1
    # Doc1 has tags 101 ("important") and 102 ("scanned").
    assert set(documents[0].tags) == {"important", "scanned"}


def test_get_documents_none_correspondent_and_type(populated_db: str) -> None:
    reader = open_reader(populated_db)
    # Doc2 has document_type_id=None.
    documents = reader.get_documents([2])
    reader.close()

    assert len(documents) == 1
    assert documents[0].document_type is None
    assert documents[0].correspondent == "Beta Ltd"


def test_get_documents_multiple_ids(populated_db: str) -> None:
    reader = open_reader(populated_db)
    documents = reader.get_documents([1, 2])
    reader.close()

    assert len(documents) == 2
    assert {document.id for document in documents} == {1, 2}


def test_get_documents_empty_ids_returns_empty(populated_db: str) -> None:
    reader = open_reader(populated_db)
    documents = reader.get_documents([])
    reader.close()

    assert documents == []


def test_get_chunks_returns_chunk_hits(populated_db: str) -> None:
    reader = open_reader(populated_db)
    # Discover a valid chunk id via vector_search first.
    hits = reader.vector_search(unit_vec(4, 0), k=1, filters=make_search_filters())
    chunk_id = hits[0].chunk_id

    chunks = reader.get_chunks([chunk_id])
    reader.close()

    assert len(chunks) == 1
    assert isinstance(chunks[0], ChunkHit)
    assert chunks[0].chunk_id == chunk_id
    assert chunks[0].document_id == 1


def test_get_chunks_empty_ids_returns_empty(populated_db: str) -> None:
    reader = open_reader(populated_db)
    chunks = reader.get_chunks([])
    reader.close()

    assert chunks == []


def test_get_taxonomy_returns_entries_for_a_kind(populated_db: str) -> None:
    reader = open_reader(populated_db)
    correspondents = reader.get_taxonomy("correspondent")
    reader.close()

    assert all(isinstance(entry, TaxonomyEntry) for entry in correspondents)
    assert all(entry.kind == "correspondent" for entry in correspondents)
    assert {entry.name for entry in correspondents} == {"Alpha Corp", "Beta Ltd"}


def test_get_taxonomy_resolves_a_single_entry_by_kind(populated_db: str) -> None:
    reader = open_reader(populated_db)
    document_types = reader.get_taxonomy("document_type")
    reader.close()

    assert len(document_types) == 1
    assert document_types[0].id == 20
    assert document_types[0].name == "Invoice"


def test_get_taxonomy_unknown_kind_returns_empty(populated_db: str) -> None:
    reader = open_reader(populated_db)
    entries = reader.get_taxonomy("not_a_real_kind")
    reader.close()

    assert entries == []


def test_get_taxonomy_empty_store_returns_empty(db_path: str) -> None:
    open_writer(db_path).close()
    reader = open_reader(db_path)
    entries = reader.get_taxonomy("tag")
    reader.close()

    assert entries == []


def test_list_facets_returns_all_kinds(populated_db: str) -> None:
    reader = open_reader(populated_db)
    facets = reader.list_facets()
    reader.close()

    assert len(facets.correspondents) == 2
    assert {entry.name for entry in facets.correspondents} == {
        "Alpha Corp",
        "Beta Ltd",
    }
    assert len(facets.document_types) == 1
    assert facets.document_types[0].name == "Invoice"
    assert len(facets.tags) == 2
    assert {entry.name for entry in facets.tags} == {"important", "scanned"}


def test_list_facets_earliest_latest(populated_db: str) -> None:
    reader = open_reader(populated_db)
    facets = reader.list_facets()
    reader.close()

    assert facets.earliest is not None
    assert facets.latest is not None
    # Doc1 created 2023, doc2 created 2024 — earliest is doc1.
    assert facets.earliest < facets.latest
    assert "2023" in facets.earliest
    assert "2024" in facets.latest


def test_list_facets_raises_schema_not_ready_on_schemaless_db(db_path: str) -> None:
    """A schema-less index raises SchemaNotReadyError, not a bare StoreError.

    StoreReader does not create the schema, so an unwritten ``db_path`` mimics
    the mid-rebuild window; the API maps this error to a 503 rather than a 500.
    """
    reader = open_reader(db_path)
    try:
        with pytest.raises(SchemaNotReadyError):
            reader.list_facets()
    finally:
        reader.close()


def test_get_stats_counts_correctly(populated_db: str) -> None:
    reader = open_reader(populated_db)
    stats = reader.get_stats()
    reader.close()

    assert isinstance(stats, IndexStats)
    assert stats.document_count == 2
    assert stats.chunk_count == 4  # 2 docs x 2 chunks each


def test_get_stats_returns_meta_fields(populated_db: str) -> None:
    reader = open_reader(populated_db)
    stats = reader.get_stats()
    reader.close()

    assert stats.last_reconcile_at == "2024-09-01T00:00:00+00:00"
    assert stats.embedding_model == "test-model"


def test_get_stats_empty_db_returns_zero_counts(db_path: str) -> None:
    open_writer(db_path).close()
    reader = open_reader(db_path)
    stats = reader.get_stats()
    reader.close()

    assert stats.document_count == 0
    assert stats.chunk_count == 0
    assert stats.last_reconcile_at is None
    assert stats.embedding_model is None
    # An empty index has no documents, so MAX(indexed_at) is NULL → None.
    assert stats.latest_indexed_at is None


def test_get_stats_raises_schema_not_ready_on_schemaless_db(db_path: str) -> None:
    reader = open_reader(db_path)
    try:
        with pytest.raises(SchemaNotReadyError):
            reader.get_stats()
    finally:
        reader.close()


def test_get_stats_reports_latest_indexed_at(populated_db: str) -> None:
    """get_stats surfaces MAX(documents.indexed_at) as the cache content signal."""
    reader = open_reader(populated_db)
    stats = reader.get_stats()
    reader.close()

    assert stats.latest_indexed_at is not None
    assert isinstance(stats.latest_indexed_at, str)


def test_latest_indexed_at_advances_on_in_place_reindex(db_path: str) -> None:
    """A re-index that keeps the doc and chunk counts still moves latest_indexed_at.

    The counts alone cannot detect such a change, so the cache version keys on
    latest_indexed_at.
    """
    from store.models import ChunkInput, DocumentMeta

    writer = open_writer(db_path)
    meta = DocumentMeta(
        id=1,
        title="Doc",
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(),
        created="2024-01-01T00:00:00+00:00",
        modified="2024-01-01T00:00:00+00:00",
        content_hash="hash-v1",
        page_count=1,
    )
    one_chunk = [
        ChunkInput(
            chunk_index=0, text="original text", page_hint=1, embedding=unit_vec(4, 0)
        )
    ]
    writer.upsert_document(meta, one_chunk)

    reader = open_reader(db_path)
    before = reader.get_stats()

    # Re-index in place: same id, same chunk COUNT (1), new content.
    writer.upsert_document(
        DocumentMeta(
            id=1,
            title="Doc",
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(),
            created="2024-01-01T00:00:00+00:00",
            modified="2024-06-01T00:00:00+00:00",
            content_hash="hash-v2",  # content changed
            page_count=1,
        ),
        [
            ChunkInput(
                chunk_index=0,
                text="corrected text",
                page_hint=1,
                embedding=unit_vec(4, 0),
            )
        ],
    )
    after = reader.get_stats()
    reader.close()
    writer.close()

    assert after.document_count == before.document_count == 1
    assert after.chunk_count == before.chunk_count == 1
    assert after.latest_indexed_at is not None
    assert before.latest_indexed_at is not None
    assert after.latest_indexed_at >= before.latest_indexed_at


def test_quick_check_returns_true_on_healthy_db(populated_db: str) -> None:
    reader = open_reader(populated_db)
    result = reader.quick_check()
    reader.close()

    assert result is True


def test_quick_check_returns_true_on_empty_db(db_path: str) -> None:
    open_writer(db_path).close()
    reader = open_reader(db_path)
    result = reader.quick_check()
    reader.close()

    assert result is True
