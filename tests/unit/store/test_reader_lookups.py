"""Tests for store.reader._lookups — look-ups and introspection.

Covers:
- get_documents resolves taxonomy names and tag names
- get_chunks returns ChunkHit objects for known chunk ids
- get_taxonomy returns the typed taxonomy rows for a kind
- list_facets returns all taxonomy kinds with earliest/latest dates
- get_stats counts documents and chunks and reports the meta fields
- quick_check returns True on a healthy DB

The ranked-retrieval behaviours live in test_reader_ranked.py — the reader's
tests mirror the store/reader/ package split (CODE_GUIDELINES §11.2).  The
``db_path``, ``populated_db`` fixtures and the ``unit_vec`` helper come from
tests/unit/store/conftest.py.
"""

from __future__ import annotations

import pytest

from store import SchemaNotReadyError
from store.models import ChunkHit, IndexedDocument, IndexStats, TaxonomyEntry
from tests.helpers.factories import make_search_filters
from tests.helpers.store import open_reader, open_writer
from tests.unit.store.conftest import unit_vec


# ---------------------------------------------------------------------------
# get_documents
# ---------------------------------------------------------------------------


def test_get_documents_resolves_taxonomy_names(populated_db: str) -> None:
    """get_documents returns IndexedDocuments with resolved correspondent and type names."""
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
    """get_documents resolves all tag names for a document."""
    reader = open_reader(populated_db)
    documents = reader.get_documents([1])
    reader.close()

    assert len(documents) == 1
    # Doc1 has tags 101 ("important") and 102 ("scanned").
    assert set(documents[0].tags) == {"important", "scanned"}


def test_get_documents_none_correspondent_and_type(populated_db: str) -> None:
    """get_documents returns None for an unset document_type."""
    reader = open_reader(populated_db)
    # Doc2 has document_type_id=None.
    documents = reader.get_documents([2])
    reader.close()

    assert len(documents) == 1
    assert documents[0].document_type is None
    assert documents[0].correspondent == "Beta Ltd"


def test_get_documents_multiple_ids(populated_db: str) -> None:
    """get_documents accepts multiple ids and returns all matching documents."""
    reader = open_reader(populated_db)
    documents = reader.get_documents([1, 2])
    reader.close()

    assert len(documents) == 2
    assert {document.id for document in documents} == {1, 2}


def test_get_documents_empty_ids_returns_empty(populated_db: str) -> None:
    """get_documents with no ids returns an empty list."""
    reader = open_reader(populated_db)
    documents = reader.get_documents([])
    reader.close()

    assert documents == []


# ---------------------------------------------------------------------------
# get_chunks
# ---------------------------------------------------------------------------


def test_get_chunks_returns_chunk_hits(populated_db: str) -> None:
    """get_chunks returns ChunkHit objects with the correct fields."""
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
    """get_chunks with no ids returns an empty list."""
    reader = open_reader(populated_db)
    chunks = reader.get_chunks([])
    reader.close()

    assert chunks == []


# ---------------------------------------------------------------------------
# get_taxonomy
# ---------------------------------------------------------------------------


def test_get_taxonomy_returns_entries_for_a_kind(populated_db: str) -> None:
    """get_taxonomy returns the typed TaxonomyEntry rows for the requested kind."""
    reader = open_reader(populated_db)
    correspondents = reader.get_taxonomy("correspondent")
    reader.close()

    assert all(isinstance(entry, TaxonomyEntry) for entry in correspondents)
    assert all(entry.kind == "correspondent" for entry in correspondents)
    assert {entry.name for entry in correspondents} == {"Alpha Corp", "Beta Ltd"}


def test_get_taxonomy_resolves_a_single_entry_by_kind(populated_db: str) -> None:
    """get_taxonomy returns the document-type rows — one in the seeded store."""
    reader = open_reader(populated_db)
    document_types = reader.get_taxonomy("document_type")
    reader.close()

    assert len(document_types) == 1
    assert document_types[0].id == 20
    assert document_types[0].name == "Invoice"


def test_get_taxonomy_unknown_kind_returns_empty(populated_db: str) -> None:
    """get_taxonomy returns an empty list for a kind with no rows."""
    reader = open_reader(populated_db)
    entries = reader.get_taxonomy("not_a_real_kind")
    reader.close()

    assert entries == []


def test_get_taxonomy_empty_store_returns_empty(db_path: str) -> None:
    """get_taxonomy on a fresh store returns an empty list, not an error."""
    open_writer(db_path).close()
    reader = open_reader(db_path)
    entries = reader.get_taxonomy("tag")
    reader.close()

    assert entries == []


# ---------------------------------------------------------------------------
# list_facets
# ---------------------------------------------------------------------------


def test_list_facets_returns_all_kinds(populated_db: str) -> None:
    """list_facets returns correspondents, document_types, and tags."""
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
    """list_facets returns the earliest and latest created dates from documents."""
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
    """A present-but-schema-less index raises the typed SchemaNotReadyError (M9).

    ``StoreReader.__init__`` connects but does not create the schema; an
    unwritten ``db_path`` therefore has no taxonomy table — the mid-rebuild
    window where the indexer has dropped and not yet recreated the tables.
    list_facets must mirror get_stats and raise SchemaNotReadyError (a 503 at
    the API), not a bare StoreError (a 500 on every search).
    """
    reader = open_reader(db_path)
    try:
        with pytest.raises(SchemaNotReadyError):
            reader.list_facets()
    finally:
        reader.close()


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


def test_get_stats_counts_correctly(populated_db: str) -> None:
    """get_stats returns the correct document and chunk counts."""
    reader = open_reader(populated_db)
    stats = reader.get_stats()
    reader.close()

    assert isinstance(stats, IndexStats)
    assert stats.document_count == 2
    assert stats.chunk_count == 4  # 2 docs x 2 chunks each


def test_get_stats_returns_meta_fields(populated_db: str) -> None:
    """get_stats returns last_reconcile_at and embedding_model from the meta table."""
    reader = open_reader(populated_db)
    stats = reader.get_stats()
    reader.close()

    assert stats.last_reconcile_at == "2024-09-01T00:00:00+00:00"
    assert stats.embedding_model == "test-model"


def test_get_stats_empty_db_returns_zero_counts(db_path: str) -> None:
    """get_stats on an empty (just-initialised) DB returns zero counts."""
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
    """get_stats on a present-but-schema-less DB raises SchemaNotReadyError.

    The sibling of the list_facets case (M9): a connected-but-not-built index
    must surface the typed not-ready fault, not a generic StoreError.
    """
    reader = open_reader(db_path)
    try:
        with pytest.raises(SchemaNotReadyError):
            reader.get_stats()
    finally:
        reader.close()


def test_get_stats_reports_latest_indexed_at(populated_db: str) -> None:
    """get_stats surfaces MAX(documents.indexed_at) as the cache content signal (M10)."""
    reader = open_reader(populated_db)
    stats = reader.get_stats()
    reader.close()

    # Two documents were upserted, each stamped with indexed_at; the field is
    # the latest of those ISO timestamps (non-None on a populated index).
    assert stats.latest_indexed_at is not None
    assert isinstance(stats.latest_indexed_at, str)


def test_latest_indexed_at_advances_on_in_place_reindex(db_path: str) -> None:
    """An in-place re-index with the SAME doc/chunk counts still moves the signal (M10).

    This is the precise staleness M10 fixes: a document re-indexed in place
    (corrected OCR, re-classification) that chunks to the same number of chunks
    leaves document_count and chunk_count identical — only indexed_at advances.
    The cache version must therefore key on latest_indexed_at, which this proves
    moves while the counts stand still.
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

    # Counts are unchanged — the in-place re-index produced the same shape.
    assert after.document_count == before.document_count == 1
    assert after.chunk_count == before.chunk_count == 1
    # …but the content signal advanced, so the cache version moves.
    assert after.latest_indexed_at is not None
    assert before.latest_indexed_at is not None
    assert after.latest_indexed_at >= before.latest_indexed_at


# ---------------------------------------------------------------------------
# quick_check
# ---------------------------------------------------------------------------


def test_quick_check_returns_true_on_healthy_db(populated_db: str) -> None:
    """quick_check returns True on a healthy, intact database."""
    reader = open_reader(populated_db)
    result = reader.quick_check()
    reader.close()

    assert result is True


def test_quick_check_returns_true_on_empty_db(db_path: str) -> None:
    """quick_check returns True even on a freshly-initialised empty DB."""
    open_writer(db_path).close()
    reader = open_reader(db_path)
    result = reader.quick_check()
    reader.close()

    assert result is True
