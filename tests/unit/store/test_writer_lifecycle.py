"""Tests for StoreWriter lifecycle, embedding-model checks and bulk operations."""

from __future__ import annotations

import sqlite3
import threading

from store.models import TaxonomyEntry
from store.schema import connect
from tests.helpers.factories import make_chunks, make_document_meta
from tests.helpers.store import open_writer


class TestConstruction:
    def test_writer_initialises_without_error(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.close()

    def test_writer_creates_schema_on_connect(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.close()
        conn = connect(db_path)
        row = conn.execute("SELECT count(*) FROM documents").fetchone()
        conn.close()
        assert row[0] == 0


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


class TestBulkDelete:
    def test_delete_more_ids_than_the_variable_limit_allows(self, db_path: str) -> None:
        writer = open_writer(db_path)
        count = 1100
        for doc_id in range(1, count + 1):
            writer.upsert_document(make_document_meta(id=doc_id), make_chunks(1))
        writer._conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 600)
        writer.delete_documents(range(1, count + 1))
        conn = writer._conn
        remaining = [
            conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("documents", "chunks", "chunks_fts")
        ]
        writer.close()
        assert remaining == [0, 0, 0]


class TestCheckEmbeddingModel:
    def test_returns_true_on_first_run(self, db_path: str) -> None:
        """With no stored model, a rebuild is needed and the model is recorded."""
        writer = open_writer(db_path, model="model-a", dimensions=4)
        result = writer.check_embedding_model()
        writer.close()
        assert result is True

    def test_returns_false_when_model_unchanged(self, db_path: str) -> None:
        writer = open_writer(db_path, model="model-a", dimensions=4)
        writer.check_embedding_model()
        result = writer.check_embedding_model()
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

        Surviving document rows would pass the reconcile's content-hash check as
        unchanged, so nothing would be re-embedded and the index would stay empty.
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

    def test_existing_openai_index_without_provider_meta_is_not_rebuilt(
        self, db_path: str
    ) -> None:
        """An index with no embedding_provider meta reads as "openai" and is kept.

        Indexes built before EMBEDDING_PROVIDER existed lack the key; treating that
        as a mismatch would wipe and fully re-embed a production index.
        """
        seed = open_writer(db_path, model="text-embedding-3-small", dimensions=1536)
        seed.write_meta("embedding_model", "text-embedding-3-small")
        seed.write_meta("embedding_dimensions", "1536")
        seed.upsert_document(make_document_meta(id=1), make_chunks(2))
        assert seed.read_meta("embedding_provider") is None  # precondition
        seed.close()

        writer = open_writer(
            db_path,
            model="text-embedding-3-small",
            dimensions=1536,
            EMBEDDING_PROVIDER="openai",
        )
        rebuild = writer.check_embedding_model()
        remaining_docs = writer.get_all_document_ids()
        writer.close()

        assert rebuild is False, "an existing OpenAI index must NOT be wiped"
        assert remaining_docs == {1}, "the document must survive the upgrade"

    def test_provider_switch_openai_to_ollama_triggers_rebuild(
        self, db_path: str
    ) -> None:
        """OpenAI and Ollama vectors are not comparable, even for one model name."""
        seed = open_writer(db_path, model="shared-model", EMBEDDING_PROVIDER="openai")
        seed.check_embedding_model()
        seed.upsert_document(make_document_meta(id=1), make_chunks(2))
        seed.close()

        writer = open_writer(db_path, model="shared-model", EMBEDDING_PROVIDER="ollama")
        rebuild = writer.check_embedding_model()
        remaining_docs = writer.get_all_document_ids()
        stored_provider = writer.read_meta("embedding_provider")
        writer.close()

        assert rebuild is True, "a provider switch must trigger a rebuild"
        assert remaining_docs == set(), "the index must be wiped on a provider switch"
        assert stored_provider == "ollama", "the new provider must be stamped"

    def test_provider_switch_ollama_to_openai_triggers_rebuild(
        self, db_path: str
    ) -> None:
        seed = open_writer(db_path, model="shared-model", EMBEDDING_PROVIDER="ollama")
        seed.check_embedding_model()
        seed.close()

        writer = open_writer(db_path, model="shared-model", EMBEDDING_PROVIDER="openai")
        rebuild = writer.check_embedding_model()
        stored_provider = writer.read_meta("embedding_provider")
        writer.close()

        assert rebuild is True
        assert stored_provider == "openai"

    def test_unchanged_ollama_identity_is_not_rebuilt(self, db_path: str) -> None:
        """A stable ollama config across boots must not re-embed each restart."""
        seed = open_writer(
            db_path, model="nomic-embed-text", EMBEDDING_PROVIDER="ollama"
        )
        seed.check_embedding_model()
        seed.close()

        writer = open_writer(
            db_path, model="nomic-embed-text", EMBEDDING_PROVIDER="ollama"
        )
        rebuild = writer.check_embedding_model()
        writer.close()

        assert rebuild is False

    def test_first_run_stamps_the_provider(self, db_path: str) -> None:
        writer = open_writer(db_path, model="model-a", EMBEDDING_PROVIDER="openai")
        writer.check_embedding_model()
        stored_provider = writer.read_meta("embedding_provider")
        writer.close()
        assert stored_provider == "openai"


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


class TestCheckpoint:
    def test_checkpoint_does_not_raise(self, db_path: str) -> None:
        writer = open_writer(db_path)
        writer.upsert_document(make_document_meta(id=1), make_chunks(2))
        writer.checkpoint()
        writer.close()


class TestConcurrentUpserts:
    def test_concurrent_upserts_do_not_corrupt(self, db_path: str) -> None:
        """The writer's internal lock must serialise concurrent upserts."""
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
            "chunks and chunks_fts diverged after concurrent upserts"
        )


def test_embedding_model_change_logs_projected_scope_at_critical(db_path: str) -> None:
    """check_embedding_model logs a CRITICAL projected-cost line on a mismatch."""
    import structlog.testing

    # Stamp the model first so the reopen is a real mismatch, not a first run.
    writer = open_writer(db_path, model="old-model")
    writer.check_embedding_model()
    writer.upsert_document(make_document_meta(id=1), make_chunks(4))
    writer.close()

    writer = open_writer(db_path, model="new-model")
    try:
        with structlog.testing.capture_logs() as captured:
            rebuilt = writer.check_embedding_model()
    finally:
        writer.close()

    assert rebuilt is True
    critical = [e for e in captured if e["event"] == "store.full_reembed_projected"]
    assert len(critical) == 1
    assert critical[0]["log_level"] == "critical"
    assert critical[0]["trigger"] == "embedding_model_change"
    assert critical[0]["document_count"] == 1
    assert critical[0]["current_chunk_count"] == 4


def test_embedding_model_match_logs_no_reembed_projection(db_path: str) -> None:
    """When the stored model matches, no projected-cost CRITICAL log is emitted."""
    import structlog.testing

    writer = open_writer(db_path, model="same-model")
    try:
        writer.check_embedding_model()
        with structlog.testing.capture_logs() as captured:
            rebuilt = writer.check_embedding_model()
    finally:
        writer.close()

    assert rebuilt is False
    assert not [e for e in captured if e["event"] == "store.full_reembed_projected"]
