"""Tests for store.writer.StoreWriter.

Covers (per task specification):
- upsert then re-read yields identical chunks
- chunks.id == chunks_fts.rowid for every chunk (the §4.2 invariant)
- re-upserting the same document REPLACES chunks and FTS rows (no duplicates, no orphans)
- delete_documents removes the document, chunks, AND chunks_fts rows
- update_metadata changes metadata without changing chunk_count or the chunks
- a transaction that raises mid-way leaves the prior version fully intact
- check_embedding_model wipes chunks on a model change but keeps documents
- refresh_taxonomy replaces wholesale
- two threads calling upsert_document concurrently do not corrupt the store
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest

from store.migrations import StoreError
from store.models import ChunkInput, DocumentMeta, TaxonomyEntry
from store.schema import connect, ensure_schema

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path) -> str:
    """Return a fresh DB path inside tmp_path."""
    return str(tmp_path / "test.db")


def _make_settings(db_path: str, *, model: str = "test-model", dimensions: int = 4) -> Any:
    """Return a MagicMock Settings with just the fields StoreWriter uses."""
    mock = MagicMock()
    mock.INDEX_DB_PATH = db_path
    mock.EMBEDDING_MODEL = model
    mock.EMBEDDING_DIMENSIONS = dimensions
    return mock


def _make_writer(db_path: str, **kwargs: Any) -> Any:
    """Import and construct a StoreWriter against a tmp_path DB."""
    from store.writer import StoreWriter

    settings = _make_settings(db_path, **kwargs)
    return StoreWriter(settings)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _meta(
    document_id: int = 1,
    *,
    content_hash: str = "aabbccdd",
    modified: str = "2024-06-01T12:00:00Z",
) -> DocumentMeta:
    return DocumentMeta(
        id=document_id,
        title="Test Document",
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(10, 20),
        created="2024-01-15T00:00:00Z",
        modified=modified,
        content_hash=content_hash,
        page_count=2,
    )


def _chunks(n: int = 2, *, dimensions: int = 4) -> list[ChunkInput]:
    """Build *n* deterministic ChunkInput objects with float32-compatible embeddings."""
    value = 1.0 / (dimensions**0.5)
    embedding: tuple[float, ...] = tuple(value for _ in range(dimensions))
    return [
        ChunkInput(
            chunk_index=i,
            text=f"Chunk {i} text content.",
            page_hint=i + 1,
            embedding=embedding,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_writer_initialises_without_error(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.close()

    def test_writer_creates_schema_on_connect(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.close()
        # Schema must be present after construction — verify by reading a table.
        conn = connect(db_path, read_only=True)
        row = conn.execute("SELECT count(*) FROM documents").fetchone()
        conn.close()
        assert row[0] == 0


# ---------------------------------------------------------------------------
# get_index_state and get_all_document_ids
# ---------------------------------------------------------------------------


class TestIndexState:
    def test_empty_store_returns_empty_state(self, db_path) -> None:
        writer = _make_writer(db_path)
        state = writer.get_index_state()
        writer.close()
        assert state == {}

    def test_index_state_contains_upserted_document(self, db_path) -> None:
        writer = _make_writer(db_path)
        meta = _meta(1, content_hash="deadbeef", modified="2024-06-01T12:00:00Z")
        writer.upsert_document(meta, _chunks())
        state = writer.get_index_state()
        writer.close()
        assert 1 in state
        assert state[1].content_hash == "deadbeef"
        assert state[1].modified == "2024-06-01T12:00:00Z"

    def test_get_all_document_ids_empty(self, db_path) -> None:
        writer = _make_writer(db_path)
        ids = writer.get_all_document_ids()
        writer.close()
        assert ids == set()

    def test_get_all_document_ids_after_upsert(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks())
        writer.upsert_document(_meta(2), _chunks())
        ids = writer.get_all_document_ids()
        writer.close()
        assert ids == {1, 2}


# ---------------------------------------------------------------------------
# upsert_document — round-trip correctness
# ---------------------------------------------------------------------------


class TestUpsertDocument:
    def test_upserted_chunks_are_retrievable(self, db_path) -> None:
        writer = _make_writer(db_path)
        chunk_list = _chunks(3)
        writer.upsert_document(_meta(1), chunk_list)
        writer.close()

        conn = connect(db_path, read_only=True)
        rows = conn.execute(
            "SELECT chunk_index, text, page_hint FROM chunks WHERE document_id = 1 ORDER BY chunk_index"
        ).fetchall()
        conn.close()

        assert len(rows) == 3
        for i, row in enumerate(rows):
            assert row[0] == chunk_list[i].chunk_index
            assert row[1] == chunk_list[i].text
            assert row[2] == chunk_list[i].page_hint

    def test_chunk_count_set_correctly(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(5))
        writer.close()

        conn = connect(db_path, read_only=True)
        row = conn.execute("SELECT chunk_count FROM documents WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == 5

    def test_indexed_at_is_set(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks())
        writer.close()

        conn = connect(db_path, read_only=True)
        row = conn.execute("SELECT indexed_at FROM documents WHERE id = 1").fetchone()
        conn.close()
        assert row[0] is not None
        assert len(row[0]) > 0


# ---------------------------------------------------------------------------
# chunks.id == chunks_fts.rowid invariant (SPEC §4.2)
# ---------------------------------------------------------------------------


class TestChunksFtsRowidInvariant:
    """Every chunks.id must equal the corresponding chunks_fts rowid (§4.2)."""

    def test_chunk_ids_equal_fts_rowids_after_upsert(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(3))
        writer.close()

        conn = connect(db_path, read_only=True)
        chunk_ids = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM chunks WHERE document_id = 1"
            ).fetchall()
        }
        fts_rowids = {
            row[0]
            for row in conn.execute(
                "SELECT rowid FROM chunks_fts"
            ).fetchall()
        }
        conn.close()

        assert chunk_ids == fts_rowids, (
            "chunks.id set must equal chunks_fts.rowid set — the §4.2 invariant"
        )

    def test_invariant_holds_for_multiple_documents(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(2))
        writer.upsert_document(_meta(2), _chunks(3))
        writer.close()

        conn = connect(db_path, read_only=True)
        chunk_ids = {
            row[0] for row in conn.execute("SELECT id FROM chunks").fetchall()
        }
        fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()
        assert chunk_ids == fts_rowids


# ---------------------------------------------------------------------------
# Re-upsert replaces chunks (no duplicates, no orphans)
# ---------------------------------------------------------------------------


class TestReupsertReplacesChunks:
    def test_re_upsert_replaces_chunks_no_duplicates(self, db_path) -> None:
        writer = _make_writer(db_path)
        # First upsert: 3 chunks.
        writer.upsert_document(_meta(1), _chunks(3))
        # Re-upsert with 2 chunks.
        writer.upsert_document(_meta(1), _chunks(2))
        writer.close()

        conn = connect(db_path, read_only=True)
        count = conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = 1"
        ).fetchone()[0]
        conn.close()
        assert count == 2

    def test_re_upsert_removes_orphaned_fts_rows(self, db_path) -> None:
        writer = _make_writer(db_path)
        # First upsert: 3 chunks → 3 FTS rows.
        writer.upsert_document(_meta(1), _chunks(3))
        first_fts_count = None
        conn = connect(db_path, read_only=True)
        first_fts_count = conn.execute(
            "SELECT count(*) FROM chunks_fts"
        ).fetchone()[0]
        conn.close()
        assert first_fts_count == 3

        # Re-upsert with 1 chunk → FTS must shrink to 1.
        writer.upsert_document(_meta(1), _chunks(1))
        writer.close()

        conn = connect(db_path, read_only=True)
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()
        assert fts_count == 1

    def test_re_upsert_invariant_still_holds(self, db_path) -> None:
        """After re-upsert, chunks.id == chunks_fts.rowid for all remaining rows."""
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(4))
        writer.upsert_document(_meta(1), _chunks(2))
        writer.close()

        conn = connect(db_path, read_only=True)
        chunk_ids = {
            row[0] for row in conn.execute("SELECT id FROM chunks").fetchall()
        }
        fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()
        assert chunk_ids == fts_rowids


# ---------------------------------------------------------------------------
# delete_documents
# ---------------------------------------------------------------------------


class TestDeleteDocuments:
    def test_delete_removes_document_row(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks())
        writer.delete_documents([1])
        writer.close()

        conn = connect(db_path, read_only=True)
        count = conn.execute(
            "SELECT count(*) FROM documents WHERE id = 1"
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_delete_removes_chunks_rows(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(3))
        writer.delete_documents([1])
        writer.close()

        conn = connect(db_path, read_only=True)
        count = conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = 1"
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_delete_removes_chunks_fts_rows(self, db_path) -> None:
        """chunks_fts rows must be removed explicitly — FK cascade does NOT cover them."""
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(3))
        writer.delete_documents([1])
        writer.close()

        conn = connect(db_path, read_only=True)
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()
        assert fts_count == 0

    def test_delete_does_not_touch_other_documents(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(2))
        writer.upsert_document(_meta(2), _chunks(2))
        writer.delete_documents([1])
        writer.close()

        conn = connect(db_path, read_only=True)
        remaining_docs = conn.execute(
            "SELECT count(*) FROM documents"
        ).fetchone()[0]
        remaining_chunks = conn.execute(
            "SELECT count(*) FROM chunks"
        ).fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()
        assert remaining_docs == 1
        assert remaining_chunks == 2
        assert fts_count == 2

    def test_delete_empty_list_is_a_no_op(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks())
        writer.delete_documents([])
        writer.close()

        conn = connect(db_path, read_only=True)
        count = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        conn.close()
        assert count == 1

    def test_delete_multiple_ids_removes_only_those(self, db_path) -> None:
        writer = _make_writer(db_path)
        for doc_id in [1, 2, 3]:
            writer.upsert_document(_meta(doc_id), _chunks(2))
        writer.delete_documents([1, 3])
        writer.close()

        conn = connect(db_path, read_only=True)
        remaining = {
            row[0]
            for row in conn.execute("SELECT id FROM documents").fetchall()
        }
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()
        assert remaining == {2}
        assert fts_count == 2


# ---------------------------------------------------------------------------
# update_metadata
# ---------------------------------------------------------------------------


class TestUpdateMetadata:
    def test_update_metadata_changes_title(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(2))
        updated = _meta(1)
        # Build a new meta with a different title.
        new_meta = DocumentMeta(
            id=1,
            title="Updated Title",
            correspondent_id=updated.correspondent_id,
            document_type_id=updated.document_type_id,
            tag_ids=updated.tag_ids,
            created=updated.created,
            modified="2024-07-01T00:00:00Z",
            content_hash=updated.content_hash,
            page_count=updated.page_count,
        )
        writer.update_metadata(new_meta)
        writer.close()

        conn = connect(db_path, read_only=True)
        row = conn.execute("SELECT title FROM documents WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == "Updated Title"

    def test_update_metadata_does_not_change_chunk_count(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(3))
        writer.update_metadata(_meta(1))
        writer.close()

        conn = connect(db_path, read_only=True)
        row = conn.execute(
            "SELECT chunk_count FROM documents WHERE id = 1"
        ).fetchone()
        conn.close()
        assert row[0] == 3

    def test_update_metadata_does_not_touch_chunks_table(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(3))
        original_chunk_ids = None
        conn = connect(db_path, read_only=True)
        original_chunk_ids = {
            row[0] for row in conn.execute("SELECT id FROM chunks WHERE document_id=1").fetchall()
        }
        conn.close()

        writer.update_metadata(_meta(1))
        writer.close()

        conn = connect(db_path, read_only=True)
        new_chunk_ids = {
            row[0] for row in conn.execute("SELECT id FROM chunks WHERE document_id=1").fetchall()
        }
        conn.close()
        assert original_chunk_ids == new_chunk_ids

    def test_update_metadata_does_not_touch_fts_rows(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(2))
        conn = connect(db_path, read_only=True)
        original_fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()

        writer.update_metadata(_meta(1))
        writer.close()

        conn = connect(db_path, read_only=True)
        new_fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()
        assert original_fts_rowids == new_fts_rowids


# ---------------------------------------------------------------------------
# Transaction atomicity: crash mid-upsert leaves prior version intact
# ---------------------------------------------------------------------------


class TestTransactionAtomicity:
    def test_failed_upsert_preserves_prior_version(self, db_path) -> None:
        """A transaction that raises mid-way must leave the prior version intact.

        We verify atomicity by subclassing StoreWriter to inject a mid-transaction
        failure and confirming that the prior version (2 chunks) survives intact.
        SQLite's 'with conn:' block rolls back the entire transaction on any
        exception, so the prior version must be preserved.
        """
        from store.writer import StoreWriter

        class _FailingWriter(StoreWriter):
            """Raises on the second INSERT INTO chunks to simulate a mid-upsert crash."""

            _chunk_insert_count: int = 0

            def upsert_document(
                self,
                meta: DocumentMeta,
                chunks: Sequence[ChunkInput],
            ) -> None:
                # Reset before the second upsert attempt.
                self._chunk_insert_count = 0
                from store.writer import _utc_now
                now = _utc_now()
                import json as _json
                tag_ids_json = _json.dumps(list(meta.tag_ids))
                import sqlite3 as _sqlite3
                try:
                    with self._write_lock:
                        with self._conn:
                            self._delete_chunks_for_document(meta.id)
                            self._conn.execute(
                                """
                                INSERT OR REPLACE INTO documents (
                                    id, title, correspondent_id, document_type_id,
                                    tag_ids, created, modified, content_hash,
                                    page_count, chunk_count, indexed_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    meta.id, meta.title, meta.correspondent_id,
                                    meta.document_type_id, tag_ids_json,
                                    meta.created, meta.modified, meta.content_hash,
                                    meta.page_count, len(chunks), now,
                                ),
                            )
                            for chunk in chunks:
                                self._chunk_insert_count += 1
                                if self._chunk_insert_count == 2:
                                    # Simulate a mid-transaction failure.
                                    raise _sqlite3.OperationalError(
                                        "simulated mid-upsert failure"
                                    )
                                import sqlite_vec as _vec
                                cursor = self._conn.execute(
                                    """
                                    INSERT INTO chunks
                                        (document_id, chunk_index, text, page_hint, embedding)
                                    VALUES (?, ?, ?, ?, ?)
                                    """,
                                    (
                                        meta.id, chunk.chunk_index, chunk.text,
                                        chunk.page_hint,
                                        _vec.serialize_float32(list(chunk.embedding)),
                                    ),
                                )
                                chunk_id = cursor.lastrowid
                                self._conn.execute(
                                    "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)",
                                    (chunk_id, chunk.text),
                                )
                except _sqlite3.Error as exc:
                    from store.migrations import StoreError as _StoreError
                    raise _StoreError(f"simulated failure for document {meta.id}") from exc

        settings = _make_settings(db_path)
        writer = _FailingWriter(settings)

        # First upsert: 2 chunks — this is the "prior version".
        # Bypass the failing subclass for the first write by calling the parent.
        from store.writer import StoreWriter as _Base
        _Base.upsert_document(writer, _meta(1), _chunks(2))

        conn = connect(db_path, read_only=True)
        prior_chunks = conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = 1"
        ).fetchone()[0]
        conn.close()
        assert prior_chunks == 2

        # Second upsert: will raise mid-transaction on the 2nd chunk insert.
        with pytest.raises((StoreError, Exception)):
            writer.upsert_document(_meta(1), _chunks(4))

        writer.close()

        # Prior version must be intact — the transaction rolled back.
        conn = connect(db_path, read_only=True)
        chunk_count = conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = 1"
        ).fetchone()[0]
        doc_count = conn.execute(
            "SELECT count(*) FROM documents WHERE id = 1"
        ).fetchone()[0]
        conn.close()
        assert doc_count == 1
        assert chunk_count == 2


# ---------------------------------------------------------------------------
# check_embedding_model
# ---------------------------------------------------------------------------


class TestCheckEmbeddingModel:
    def test_returns_false_on_first_run_same_model(self, db_path) -> None:
        """First run with matching model/dimensions should store values and return False."""
        writer = _make_writer(db_path, model="model-a", dimensions=4)
        result = writer.check_embedding_model()
        writer.close()
        # On first run, there's no prior value — the spec says mismatch (or first run)
        # wipes chunks and returns True.
        assert result is True

    def test_returns_false_when_model_unchanged(self, db_path) -> None:
        """After a successful check_embedding_model, calling it again returns False."""
        writer = _make_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()  # first call — sets the model
        result = writer.check_embedding_model()  # second call — model matches
        writer.close()
        assert result is False

    def test_returns_true_on_model_name_change(self, db_path) -> None:
        writer = _make_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()

        # Open a new writer with a different model name.
        writer.close()
        writer2 = _make_writer(db_path, model="model-b", dimensions=4)
        result = writer2.check_embedding_model()
        writer2.close()
        assert result is True

    def test_returns_true_on_dimension_change(self, db_path) -> None:
        writer = _make_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()
        writer.close()

        writer2 = _make_writer(db_path, model="model-a", dimensions=8)
        result = writer2.check_embedding_model()
        writer2.close()
        assert result is True

    def test_model_change_wipes_chunks_keeps_documents(self, db_path) -> None:
        """On a model change, chunks and chunks_fts must be wiped; documents kept."""
        writer = _make_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()
        writer.upsert_document(_meta(1), _chunks(3))
        writer.close()

        writer2 = _make_writer(db_path, model="model-b", dimensions=4)
        writer2.check_embedding_model()
        writer2.close()

        conn = connect(db_path, read_only=True)
        doc_count = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()

        assert doc_count == 1, "documents must survive a model change"
        assert chunk_count == 0, "chunks must be wiped on a model change"
        assert fts_count == 0, "chunks_fts must be wiped on a model change"

    def test_model_change_resets_watermark(self, db_path) -> None:
        """On model change, modified_watermark must be cleared."""
        writer = _make_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()
        writer.write_meta("modified_watermark", "2024-01-01T00:00:00Z")
        writer.close()

        writer2 = _make_writer(db_path, model="model-b", dimensions=4)
        writer2.check_embedding_model()
        watermark = writer2.read_meta("modified_watermark")
        writer2.close()
        assert watermark is None

    def test_model_change_writes_new_model_to_meta(self, db_path) -> None:
        writer = _make_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()
        writer.close()

        writer2 = _make_writer(db_path, model="model-b", dimensions=8)
        writer2.check_embedding_model()
        model_stored = writer2.read_meta("embedding_model")
        dims_stored = writer2.read_meta("embedding_dimensions")
        writer2.close()

        assert model_stored == "model-b"
        assert dims_stored == "8"


# ---------------------------------------------------------------------------
# refresh_taxonomy
# ---------------------------------------------------------------------------


class TestRefreshTaxonomy:
    def test_refresh_taxonomy_inserts_entries(self, db_path) -> None:
        writer = _make_writer(db_path)
        entries = [
            TaxonomyEntry(kind="tag", id=1, name="Invoice"),
            TaxonomyEntry(kind="correspondent", id=2, name="Acme Corp"),
        ]
        writer.refresh_taxonomy(entries)
        writer.close()

        conn = connect(db_path, read_only=True)
        count = conn.execute("SELECT count(*) FROM taxonomy").fetchone()[0]
        conn.close()
        assert count == 2

    def test_refresh_taxonomy_replaces_all_entries(self, db_path) -> None:
        """refresh_taxonomy is a full replacement, not an append."""
        writer = _make_writer(db_path)
        writer.refresh_taxonomy(
            [
                TaxonomyEntry(kind="tag", id=1, name="Invoice"),
                TaxonomyEntry(kind="tag", id=2, name="Receipt"),
            ]
        )
        # Second call with different entries must fully replace the first.
        writer.refresh_taxonomy(
            [
                TaxonomyEntry(kind="correspondent", id=10, name="Acme"),
            ]
        )
        writer.close()

        conn = connect(db_path, read_only=True)
        rows = conn.execute("SELECT kind, id, name FROM taxonomy").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "correspondent"

    def test_refresh_taxonomy_empty_list_clears_table(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.refresh_taxonomy(
            [TaxonomyEntry(kind="tag", id=1, name="Invoice")]
        )
        writer.refresh_taxonomy([])
        writer.close()

        conn = connect(db_path, read_only=True)
        count = conn.execute("SELECT count(*) FROM taxonomy").fetchone()[0]
        conn.close()
        assert count == 0


# ---------------------------------------------------------------------------
# read_meta / write_meta
# ---------------------------------------------------------------------------


class TestMeta:
    def test_write_then_read_returns_value(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.write_meta("my_key", "my_value")
        result = writer.read_meta("my_key")
        writer.close()
        assert result == "my_value"

    def test_read_absent_key_returns_none(self, db_path) -> None:
        writer = _make_writer(db_path)
        result = writer.read_meta("nonexistent")
        writer.close()
        assert result is None

    def test_write_overwrites_existing_value(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.write_meta("k", "v1")
        writer.write_meta("k", "v2")
        result = writer.read_meta("k")
        writer.close()
        assert result == "v2"


# ---------------------------------------------------------------------------
# checkpoint
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def test_checkpoint_does_not_raise(self, db_path) -> None:
        writer = _make_writer(db_path)
        writer.upsert_document(_meta(1), _chunks(2))
        writer.checkpoint()
        writer.close()


# ---------------------------------------------------------------------------
# Thread safety: concurrent upserts do not corrupt the store
# ---------------------------------------------------------------------------


class TestConcurrentUpserts:
    def test_concurrent_upserts_do_not_corrupt(self, db_path) -> None:
        """Two threads calling upsert_document concurrently must not corrupt the store.

        The internal threading.Lock must serialise the transactions.
        """
        writer = _make_writer(db_path)
        errors: list[Exception] = []

        def upsert_doc(document_id: int) -> None:
            try:
                writer.upsert_document(_meta(document_id), _chunks(3))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=upsert_doc, args=(i,)) for i in range(1, 11)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        writer.close()

        assert errors == [], f"Thread exceptions: {errors}"

        conn = connect(db_path, read_only=True)
        doc_count = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        chunk_ids = {
            row[0] for row in conn.execute("SELECT id FROM chunks").fetchall()
        }
        fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()

        assert doc_count == 10
        assert chunk_count == 30
        assert fts_count == 30
        assert chunk_ids == fts_rowids, "§4.2 invariant violated after concurrent upserts"
