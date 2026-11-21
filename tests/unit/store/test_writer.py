"""Tests for the StoreWriter per-document write path."""

from __future__ import annotations

import sqlite3

import pytest

from store.migrations import StoreError
from store.schema import connect
from tests.helpers.factories import make_chunks, make_document_meta
from tests.helpers.store import open_writer


class TestUpsertDocument:
    def test_upserted_chunks_are_retrievable(self, db_path: str) -> None:
        writer = open_writer(db_path)
        chunk_list = make_chunks(3)
        writer.upsert_document(make_document_meta(id=1), chunk_list)
        writer.close()

        conn = connect(db_path)
        rows = conn.execute(
            "SELECT chunk_index, text, page_hint FROM chunks "
            "WHERE document_id = 1 ORDER BY chunk_index"
        ).fetchall()
        conn.close()

        assert len(rows) == 3
        for i, row in enumerate(rows):
            assert row[0] == chunk_list[i].chunk_index
            assert row[1] == chunk_list[i].text
            assert row[2] == chunk_list[i].page_hint

    def test_chunk_count_set_correctly(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(5))
        writer.close()

        conn = connect(db_path)
        row = conn.execute("SELECT chunk_count FROM documents WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == 5

    def test_indexed_at_is_set(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks())
        writer.close()

        conn = connect(db_path)
        row = conn.execute("SELECT indexed_at FROM documents WHERE id = 1").fetchone()
        conn.close()
        assert row[0] is not None
        assert len(row[0]) > 0


class TestChunksFtsRowidInvariant:
    """Every chunks.id must equal its chunks_fts rowid."""

    def test_chunk_ids_equal_fts_rowids_after_upsert(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(3))
        writer.close()

        conn = connect(db_path)
        chunk_ids = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM chunks WHERE document_id = 1"
            ).fetchall()
        }
        fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()

        assert chunk_ids == fts_rowids, "chunks.id set must equal chunks_fts.rowid set"

    def test_invariant_holds_for_multiple_documents(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(2))
        writer.upsert_document(make_document_meta(id=2), make_chunks(3))
        writer.close()

        conn = connect(db_path)
        chunk_ids = {row[0] for row in conn.execute("SELECT id FROM chunks").fetchall()}
        fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()
        assert chunk_ids == fts_rowids


class TestReupsertReplacesChunks:
    def test_re_upsert_replaces_chunks_no_duplicates(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(3))
        writer.upsert_document(make_document_meta(id=1), make_chunks(2))
        writer.close()

        conn = connect(db_path)
        count = conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = 1"
        ).fetchone()[0]
        conn.close()
        assert count == 2

    def test_re_upsert_removes_orphaned_fts_rows(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(3))
        conn = connect(db_path)
        first_fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()
        assert first_fts_count == 3

        writer.upsert_document(make_document_meta(id=1), make_chunks(1))
        writer.close()

        conn = connect(db_path)
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()
        assert fts_count == 1

    def test_re_upsert_invariant_still_holds(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(4))
        writer.upsert_document(make_document_meta(id=1), make_chunks(2))
        writer.close()

        conn = connect(db_path)
        chunk_ids = {row[0] for row in conn.execute("SELECT id FROM chunks").fetchall()}
        fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()
        assert chunk_ids == fts_rowids


class TestDeleteDocuments:
    def test_delete_removes_document_row(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks())
        writer.delete_documents([1])
        writer.close()

        conn = connect(db_path)
        count = conn.execute("SELECT count(*) FROM documents WHERE id = 1").fetchone()[
            0
        ]
        conn.close()
        assert count == 0

    def test_delete_removes_chunks_rows(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(3))
        writer.delete_documents([1])
        writer.close()

        conn = connect(db_path)
        count = conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = 1"
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_delete_removes_chunks_fts_rows(self, db_path: str) -> None:
        """chunks_fts rows must be removed explicitly; the FK cascade misses them."""
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(3))
        writer.delete_documents([1])
        writer.close()

        conn = connect(db_path)
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()
        assert fts_count == 0

    def test_delete_does_not_touch_other_documents(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(2))
        writer.upsert_document(make_document_meta(id=2), make_chunks(2))
        writer.delete_documents([1])
        writer.close()

        conn = connect(db_path)
        remaining_docs = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        remaining_chunks = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()
        assert remaining_docs == 1
        assert remaining_chunks == 2
        assert fts_count == 2

    def test_delete_empty_list_is_a_no_op(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks())
        writer.delete_documents([])
        writer.close()

        conn = connect(db_path)
        count = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        conn.close()
        assert count == 1

    def test_delete_multiple_ids_removes_only_those(self, db_path: str) -> None:
        writer = open_writer(db_path)
        for doc_id in [1, 2, 3]:
            writer.upsert_document(make_document_meta(id=doc_id), make_chunks(2))
        writer.delete_documents([1, 3])
        writer.close()

        conn = connect(db_path)
        remaining = {
            row[0] for row in conn.execute("SELECT id FROM documents").fetchall()
        }
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()
        assert remaining == {2}
        assert fts_count == 2


class TestUpdateMetadata:
    def test_update_metadata_changes_title(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(2))
        writer.update_metadata(
            make_document_meta(
                id=1, title="Updated Title", modified="2024-07-01T00:00:00Z"
            )
        )
        writer.close()

        conn = connect(db_path)
        row = conn.execute("SELECT title FROM documents WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == "Updated Title"

    def test_update_metadata_does_not_change_chunk_count(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(3))
        writer.update_metadata(make_document_meta(id=1))
        writer.close()

        conn = connect(db_path)
        row = conn.execute("SELECT chunk_count FROM documents WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == 3

    def test_update_metadata_does_not_touch_chunks_table(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(3))
        conn = connect(db_path)
        original_chunk_ids = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM chunks WHERE document_id=1"
            ).fetchall()
        }
        conn.close()

        writer.update_metadata(make_document_meta(id=1))
        writer.close()

        conn = connect(db_path)
        new_chunk_ids = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM chunks WHERE document_id=1"
            ).fetchall()
        }
        conn.close()
        assert original_chunk_ids == new_chunk_ids

    def test_update_metadata_does_not_touch_fts_rows(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(2))
        conn = connect(db_path)
        original_fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()

        writer.update_metadata(make_document_meta(id=1))
        writer.close()

        conn = connect(db_path)
        new_fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()
        assert original_fts_rowids == new_fts_rowids

    def test_update_metadata_raises_when_document_is_absent(self, db_path: str) -> None:
        """A metadata-only update of a missing document raises.

        If the row was pruned concurrently the UPDATE affects 0 rows; reporting
        success would leave the index out of step with the reconciler's state.
        """
        writer = open_writer(db_path)
        try:
            with pytest.raises(StoreError, match="42"):
                writer.update_metadata(make_document_meta(id=42))
        finally:
            writer.close()

    def test_update_metadata_succeeds_for_present_document(self, db_path: str) -> None:
        """The rowcount guard does not break the normal present-document path."""
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=7), make_chunks(2))
        writer.update_metadata(make_document_meta(id=7, title="New"))
        writer.close()

        conn = connect(db_path)
        row = conn.execute("SELECT title FROM documents WHERE id = 7").fetchone()
        conn.close()
        assert row[0] == "New"


class TestTransactionAtomicity:
    def test_failed_upsert_preserves_prior_version(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mid-transaction failure in upsert_document rolls back cleanly.

        serialize_float32 is patched to raise on its second call, so the real
        upsert fails partway through.
        """
        import sqlite_vec as _vec

        import store.writer as writer_mod

        writer = open_writer(db_path)

        writer.upsert_document(make_document_meta(id=1), make_chunks(2))

        conn = connect(db_path)
        prior_chunks = conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = 1"
        ).fetchone()[0]
        prior_fts = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()
        assert prior_chunks == 2
        assert prior_fts == 2

        call_count: list[int] = [0]
        original_serialize = _vec.serialize_float32

        def _failing_serialize(data: list[float]) -> bytes:
            call_count[0] += 1
            if call_count[0] == 2:
                raise sqlite3.OperationalError("simulated mid-upsert failure")
            return original_serialize(data)

        monkeypatch.setattr(
            writer_mod.sqlite_vec, "serialize_float32", _failing_serialize
        )

        # The writer wraps the sqlite3 error in StoreError.
        with pytest.raises(StoreError):
            writer.upsert_document(make_document_meta(id=1), make_chunks(4))

        writer.close()

        conn = connect(db_path)
        chunk_count = conn.execute(
            "SELECT count(*) FROM chunks WHERE document_id = 1"
        ).fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        doc_count = conn.execute(
            "SELECT count(*) FROM documents WHERE id = 1"
        ).fetchone()[0]
        conn.close()

        assert doc_count == 1, "document row must survive the rolled-back transaction"
        assert chunk_count == 2, "prior 2 chunks must be restored, not the partial 4"
        assert fts_count == 2, (
            "prior 2 FTS rows must be restored, not the partial write"
        )
