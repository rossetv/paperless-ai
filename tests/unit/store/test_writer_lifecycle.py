"""Tests for store.writer.StoreWriter — lifecycle and bulk operations.

Covers the writer behaviours outside the per-document write path:
- construction creates the schema
- get_index_state / get_all_document_ids report indexed documents
- check_embedding_model wipes everything (incl. documents) on a model change,
  so the next reconcile actually re-embeds rather than a metadata-only pass
- refresh_taxonomy replaces the taxonomy wholesale
- read_meta / write_meta round-trip
- checkpoint runs without error
- two threads calling upsert_document concurrently do not corrupt the store

The per-document upsert / delete / update_metadata behaviours live in
test_writer.py — the writer's tests are split across two files for the
500-line ceiling (CODE_GUIDELINES §3.1).  Shared fixtures (``db_path``) come
from tests/unit/store/conftest.py.
"""

from __future__ import annotations

import threading

from store.models import TaxonomyEntry
from store.schema import connect
from tests.helpers.factories import make_chunks, make_document_meta
from tests.helpers.store import open_writer


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_writer_initialises_without_error(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.close()

    def test_writer_creates_schema_on_connect(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.close()
        # Schema must be present after construction — verify by reading a table.
        conn = connect(db_path)
        row = conn.execute("SELECT count(*) FROM documents").fetchone()
        conn.close()
        assert row[0] == 0


# ---------------------------------------------------------------------------
# get_index_state and get_all_document_ids
# ---------------------------------------------------------------------------


class TestIndexState:
    def test_empty_store_returns_empty_state(self, db_path: str) -> None:
        writer = open_writer(db_path)
        state = writer.get_index_state()
        writer.close()
        assert state == {}

    def test_index_state_contains_upserted_document(self, db_path: str) -> None:
        writer = open_writer(db_path)
        meta = make_document_meta(
            id=1, content_hash="deadbeef", modified="2024-06-01T12:00:00Z"
        )
        writer.upsert_document(meta, make_chunks())
        state = writer.get_index_state()
        writer.close()
        assert 1 in state
        assert state[1].content_hash == "deadbeef"
        assert state[1].modified == "2024-06-01T12:00:00Z"

    def test_get_all_document_ids_empty(self, db_path: str) -> None:
        writer = open_writer(db_path)
        ids = writer.get_all_document_ids()
        writer.close()
        assert ids == set()

    def test_get_all_document_ids_after_upsert(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks())
        writer.upsert_document(make_document_meta(id=2), make_chunks())
        ids = writer.get_all_document_ids()
        writer.close()
        assert ids == {1, 2}


# ---------------------------------------------------------------------------
# check_embedding_model
# ---------------------------------------------------------------------------


class TestCheckEmbeddingModel:
    def test_returns_true_on_first_run(self, db_path: str) -> None:
        """First run has no prior value — the spec says first run returns True
        (a rebuild is needed) and records the model."""
        writer = open_writer(db_path, model="model-a", dimensions=4)
        result = writer.check_embedding_model()
        writer.close()
        assert result is True

    def test_returns_false_when_model_unchanged(self, db_path: str) -> None:
        """After a successful check_embedding_model, calling it again returns False."""
        writer = open_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()  # first call — sets the model
        result = writer.check_embedding_model()  # second call — model matches
        writer.close()
        assert result is False

    def test_returns_true_on_model_name_change(self, db_path: str) -> None:
        writer = open_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()
        writer.close()

        writer2 = open_writer(db_path, model="model-b", dimensions=4)
        result = writer2.check_embedding_model()
        writer2.close()
        assert result is True

    def test_returns_true_on_dimension_change(self, db_path: str) -> None:
        writer = open_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()
        writer.close()

        writer2 = open_writer(db_path, model="model-a", dimensions=8)
        result = writer2.check_embedding_model()
        writer2.close()
        assert result is True

    def test_model_change_wipes_everything_so_the_reembed_runs(
        self, db_path: str
    ) -> None:
        """A model change must wipe documents too, not just chunks.

        Regression (IDX): keeping the document rows lets the reconcile's
        content-hash check classify each document as unchanged and take a
        metadata-only pass — re-embedding nothing and leaving the index
        permanently empty. Documents, chunks, and chunks_fts must all be wiped
        so the next sync re-fetches and re-embeds the whole archive.
        """
        writer = open_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()
        writer.upsert_document(make_document_meta(id=1), make_chunks(3))
        writer.close()

        writer2 = open_writer(db_path, model="model-b", dimensions=4)
        writer2.check_embedding_model()
        writer2.close()

        conn = connect(db_path)
        doc_count = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        conn.close()

        assert doc_count == 0, "documents must be wiped so the re-embed runs"
        assert chunk_count == 0, "chunks must be wiped on a model change"
        assert fts_count == 0, "chunks_fts must be wiped on a model change"

    def test_model_change_resets_watermark(self, db_path: str) -> None:
        """On model change, modified_watermark must be cleared."""
        writer = open_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()
        writer.write_meta("modified_watermark", "2024-01-01T00:00:00Z")
        writer.close()

        writer2 = open_writer(db_path, model="model-b", dimensions=4)
        writer2.check_embedding_model()
        watermark = writer2.read_meta("modified_watermark")
        writer2.close()
        assert watermark is None

    def test_model_change_writes_new_model_to_meta(self, db_path: str) -> None:
        writer = open_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()
        writer.close()

        writer2 = open_writer(db_path, model="model-b", dimensions=8)
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
    def test_refresh_taxonomy_inserts_entries(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.refresh_taxonomy(
            [
                TaxonomyEntry(kind="tag", id=1, name="Invoice"),
                TaxonomyEntry(kind="correspondent", id=2, name="Acme Corp"),
            ]
        )
        writer.close()

        conn = connect(db_path)
        count = conn.execute("SELECT count(*) FROM taxonomy").fetchone()[0]
        conn.close()
        assert count == 2

    def test_refresh_taxonomy_replaces_all_entries(self, db_path: str) -> None:
        """refresh_taxonomy is a full replacement, not an append."""
        writer = open_writer(db_path)
        writer.refresh_taxonomy(
            [
                TaxonomyEntry(kind="tag", id=1, name="Invoice"),
                TaxonomyEntry(kind="tag", id=2, name="Receipt"),
            ]
        )
        # Second call with different entries must fully replace the first.
        writer.refresh_taxonomy(
            [TaxonomyEntry(kind="correspondent", id=10, name="Acme")]
        )
        writer.close()

        conn = connect(db_path)
        rows = conn.execute("SELECT kind, id, name FROM taxonomy").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "correspondent"

    def test_refresh_taxonomy_empty_list_clears_table(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.refresh_taxonomy([TaxonomyEntry(kind="tag", id=1, name="Invoice")])
        writer.refresh_taxonomy([])
        writer.close()

        conn = connect(db_path)
        count = conn.execute("SELECT count(*) FROM taxonomy").fetchone()[0]
        conn.close()
        assert count == 0


# ---------------------------------------------------------------------------
# read_meta / write_meta
# ---------------------------------------------------------------------------


class TestMeta:
    def test_write_then_read_returns_value(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.write_meta("my_key", "my_value")
        result = writer.read_meta("my_key")
        writer.close()
        assert result == "my_value"

    def test_read_absent_key_returns_none(self, db_path: str) -> None:
        writer = open_writer(db_path)
        result = writer.read_meta("nonexistent")
        writer.close()
        assert result is None

    def test_write_overwrites_existing_value(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.write_meta("k", "v1")
        writer.write_meta("k", "v2")
        result = writer.read_meta("k")
        writer.close()
        assert result == "v2"


# ---------------------------------------------------------------------------
# checkpoint
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def test_checkpoint_does_not_raise(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(2))
        writer.checkpoint()
        writer.close()


# ---------------------------------------------------------------------------
# Thread safety: concurrent upserts do not corrupt the store
# ---------------------------------------------------------------------------


class TestConcurrentUpserts:
    def test_concurrent_upserts_do_not_corrupt(self, db_path: str) -> None:
        """Two threads calling upsert_document concurrently must not corrupt the store.

        The internal threading.Lock must serialise the transactions.
        """
        writer = open_writer(db_path)
        errors: list[Exception] = []

        def upsert_doc(document_id: int) -> None:
            try:
                writer.upsert_document(
                    make_document_meta(id=document_id), make_chunks(3)
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=upsert_doc, args=(i,)) for i in range(1, 11)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        writer.close()

        assert errors == [], f"Thread exceptions: {errors}"

        conn = connect(db_path)
        doc_count = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        chunk_ids = {row[0] for row in conn.execute("SELECT id FROM chunks").fetchall()}
        fts_rowids = {
            row[0] for row in conn.execute("SELECT rowid FROM chunks_fts").fetchall()
        }
        conn.close()

        assert doc_count == 10
        assert chunk_count == 30
        assert fts_count == 30
        assert chunk_ids == fts_rowids, (
            "§4.2 invariant violated after concurrent upserts"
        )


# ---------------------------------------------------------------------------
# Re-embed cost-guard — CRITICAL projected-scope log before the model-change wipe
# ---------------------------------------------------------------------------


def test_embedding_model_change_logs_projected_scope_at_critical(db_path: str) -> None:
    """check_embedding_model logs a CRITICAL projected-cost line on a mismatch (IDX-04)."""
    import structlog.testing

    # Seed an index under model "old-model".  check_embedding_model writes the
    # embedding_model meta so the reopen below sees a genuine mismatch (not a
    # first-run None), then upsert the chunks whose count the log projects.
    writer = open_writer(db_path, model="old-model")
    writer.check_embedding_model()  # writes embedding_model meta = "old-model"
    writer.upsert_document(make_document_meta(id=1), make_chunks(4))
    writer.close()

    # Reopen under a DIFFERENT model → mismatch → wipe path.
    writer = open_writer(db_path, model="new-model")
    try:
        with structlog.testing.capture_logs() as captured:
            rebuilt = writer.check_embedding_model()
    finally:
        writer.close()

    assert rebuilt is True  # behaviour unchanged: a mismatch still rebuilds
    critical = [e for e in captured if e["event"] == "store.full_reembed_projected"]
    assert len(critical) == 1
    assert critical[0]["log_level"] == "critical"
    assert critical[0]["trigger"] == "embedding_model_change"
    assert critical[0]["document_count"] == 1
    assert critical[0]["current_chunk_count"] == 4


def test_embedding_model_match_logs_no_reembed_projection(db_path: str) -> None:
    """When the model matches, no wipe and no projected-cost CRITICAL log.

    The first call writes the model meta (a first-run mismatch); the assertion
    is on the SECOND call, where the stored model already matches so no wipe and
    no re-embed projection happen.
    """
    import structlog.testing

    writer = open_writer(db_path, model="same-model")
    try:
        writer.check_embedding_model()  # first run — writes embedding_model meta
        with structlog.testing.capture_logs() as captured:
            rebuilt = writer.check_embedding_model()  # model now matches
    finally:
        writer.close()

    assert rebuilt is False
    assert not [e for e in captured if e["event"] == "store.full_reembed_projected"]
