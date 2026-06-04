"""Tests for store.schema and store.models.

Covers:
- connect() opens a WAL-mode DB with foreign_keys ON
- sqlite-vec extension loads (vec_version() succeeds)
- _SCHEMA / ensure_schema() is idempotent (safe to apply twice)
- Every table and index from SPEC §4.1 exists after ensure_schema()
- Dataclasses are frozen (attribute mutation raises FrozenInstanceError)
"""

from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError

import pytest

from store.schema import SCHEMA_VERSION, _SCHEMA, connect, ensure_schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_names(conn: sqlite3.Connection) -> set[str]:
    """Return names of all non-internal tables (real + virtual) in the DB."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow') AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    """Return names of all indexes in the DB."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()
    return {row[0] for row in rows}


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------


class TestConnect:
    """connect() sets up a usable SQLite connection with the required pragmas."""

    def test_opens_database_at_given_path(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")
        conn = connect(db_path)
        try:
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
            row = conn.execute("SELECT x FROM t").fetchone()
            assert row[0] == 1
        finally:
            conn.close()

    def test_journal_mode_is_wal(self, tmp_path) -> None:
        db_path = str(tmp_path / "wal.db")
        conn = connect(db_path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"
        finally:
            conn.close()

    def test_foreign_keys_are_on(self, tmp_path) -> None:
        db_path = str(tmp_path / "fk.db")
        conn = connect(db_path)
        try:
            fk_status = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk_status == 1
        finally:
            conn.close()

    def test_performance_pragmas_applied(self, tmp_path) -> None:
        """connect() tunes the page cache, mmap, and temp store for read speed.

        These are advisory performance pragmas, not correctness ones, so they
        are pinned here to stop a future edit silently dropping the measured
        ~40% vector-scan win.
        """
        db_path = str(tmp_path / "perf.db")
        conn = connect(db_path)
        try:
            # -262144 KiB == 256 MiB page cache (negative => KiB units).
            assert conn.execute("PRAGMA cache_size").fetchone()[0] == -262144
            # 512 MiB of memory-mapped reads enabled (default is 0 == off).
            assert conn.execute("PRAGMA mmap_size").fetchone()[0] == 536870912
            # temp_store=MEMORY is reported as 2.
            assert conn.execute("PRAGMA temp_store").fetchone()[0] == 2
        finally:
            conn.close()

    def test_fresh_database_uses_8k_page_size(self, tmp_path) -> None:
        """A freshly created index uses an 8 KiB page so a 6 KiB embedding BLOB
        does not spill onto an overflow-page chain. page_size only takes on a
        new value before the first table exists, so this asserts the ordering
        in connect() (page_size before journal_mode=WAL) is correct."""
        db_path = str(tmp_path / "pagesize.db")
        conn = connect(db_path)
        try:
            conn.execute("CREATE TABLE t (x INTEGER)")  # materialise page 1
            assert conn.execute("PRAGMA page_size").fetchone()[0] == 8192
        finally:
            conn.close()

    def test_connect_always_opens_read_write(self, tmp_path) -> None:
        """Every connect() opens a read-write connection, even a re-open.

        connect() takes no read-only mode: a connection-level mode=ro URI is
        deliberately avoided because a read-only SQLite connection cannot
        maintain the WAL -shm coordination file while a separate writer process
        is live.  Read-only access for the search server is enforced by the
        StoreReader API surface and the indexer's flock, not by the URI
        (SPEC §3.2).  A second connection to an existing file must therefore
        still accept writes.
        """
        db_path = str(tmp_path / "reopen.db")
        # Create the DB first so the re-open has an existing file to open.
        conn_first = connect(db_path)
        conn_first.close()

        conn = connect(db_path)
        try:
            # The re-opened connection is a normal read-write one — it writes.
            conn.execute("CREATE TABLE t (x INTEGER)")
        finally:
            conn.close()

    def test_sqlite_vec_extension_loaded(self, tmp_path) -> None:
        """vec_version() must succeed after connect()."""
        db_path = str(tmp_path / "vec.db")
        conn = connect(db_path)
        try:
            row = conn.execute("SELECT vec_version()").fetchone()
            assert row is not None
            assert row[0]  # non-empty version string
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# ensure_schema() — tables and indexes
# ---------------------------------------------------------------------------


class TestEnsureSchema:
    """ensure_schema() creates the full schema idempotently."""

    @pytest.fixture()
    def conn(self, tmp_path) -> sqlite3.Connection:
        db_path = str(tmp_path / "schema.db")
        c = connect(db_path)
        yield c
        c.close()

    def test_ensure_schema_is_idempotent(self, conn) -> None:
        """Applying the schema twice must not raise."""
        ensure_schema(conn)
        ensure_schema(conn)  # second application must be a no-op

    def test_documents_table_exists(self, conn) -> None:
        ensure_schema(conn)
        assert "documents" in _table_names(conn)

    def test_taxonomy_table_exists(self, conn) -> None:
        ensure_schema(conn)
        assert "taxonomy" in _table_names(conn)

    def test_chunks_table_exists(self, conn) -> None:
        ensure_schema(conn)
        assert "chunks" in _table_names(conn)

    def test_chunks_fts_table_exists(self, conn) -> None:
        ensure_schema(conn)
        # FTS5 tables appear as multiple names in sqlite_master; the main
        # virtual table is 'chunks_fts'.
        tables = _table_names(conn)
        assert "chunks_fts" in tables

    def test_meta_table_exists(self, conn) -> None:
        ensure_schema(conn)
        assert "meta" in _table_names(conn)

    def test_documents_indexes_exist(self, conn) -> None:
        """All four column indexes on documents must be created."""
        ensure_schema(conn)
        indexes = _index_names(conn)
        assert "idx_documents_modified" in indexes
        assert "idx_documents_correspondent_id" in indexes
        assert "idx_documents_document_type_id" in indexes
        assert "idx_documents_created" in indexes

    def test_chunks_document_id_index_exists(self, conn) -> None:
        ensure_schema(conn)
        assert "idx_chunks_document_id" in _index_names(conn)

    def test_documents_columns(self, conn) -> None:
        """documents table must have all columns from SPEC §4.1."""
        ensure_schema(conn)
        info = conn.execute("PRAGMA table_info(documents)").fetchall()
        column_names = {row[1] for row in info}
        expected = {
            "id",
            "title",
            "correspondent_id",
            "document_type_id",
            "tag_ids",
            "created",
            "modified",
            "content_hash",
            "page_count",
            "chunk_count",
            "indexed_at",
        }
        assert expected <= column_names

    def test_taxonomy_columns(self, conn) -> None:
        ensure_schema(conn)
        info = conn.execute("PRAGMA table_info(taxonomy)").fetchall()
        column_names = {row[1] for row in info}
        assert {"kind", "id", "name"} <= column_names

    def test_chunks_columns(self, conn) -> None:
        ensure_schema(conn)
        info = conn.execute("PRAGMA table_info(chunks)").fetchall()
        column_names = {row[1] for row in info}
        expected = {
            "id",
            "document_id",
            "chunk_index",
            "text",
            "page_hint",
            "embedding",
        }
        assert expected <= column_names

    def test_meta_columns(self, conn) -> None:
        ensure_schema(conn)
        info = conn.execute("PRAGMA table_info(meta)").fetchall()
        column_names = {row[1] for row in info}
        assert {"key", "value"} <= column_names

    def test_schema_version_constant_is_one(self) -> None:
        assert SCHEMA_VERSION == 1

    def test_schema_string_not_empty(self) -> None:
        assert _SCHEMA.strip()


# ---------------------------------------------------------------------------
# Dataclass immutability
# ---------------------------------------------------------------------------


class TestDataclassImmutability:
    """Every model dataclass must be frozen — mutation raises FrozenInstanceError."""

    def test_index_state_is_frozen(self) -> None:
        from store.models import IndexState

        obj = IndexState(modified="2024-01-01T00:00:00Z", content_hash="abc")
        with pytest.raises(FrozenInstanceError):
            obj.modified = "2025-01-01T00:00:00Z"  # type: ignore[misc]

    def test_document_meta_is_frozen(self) -> None:
        from store.models import DocumentMeta

        obj = DocumentMeta(
            id=1,
            title="Test",
            correspondent_id=None,
            document_type_id=None,
            tag_ids=(1, 2),
            created=None,
            modified="2024-01-01T00:00:00Z",
            content_hash="deadbeef",
            page_count=None,
        )
        with pytest.raises(FrozenInstanceError):
            obj.title = "mutated"  # type: ignore[misc]

    def test_chunk_input_is_frozen(self) -> None:
        from store.models import ChunkInput

        obj = ChunkInput(
            chunk_index=0, text="hello", page_hint=None, embedding=(0.1, 0.2)
        )
        with pytest.raises(FrozenInstanceError):
            obj.text = "world"  # type: ignore[misc]

    def test_taxonomy_entry_is_frozen(self) -> None:
        from store.models import TaxonomyEntry

        obj = TaxonomyEntry(kind="tag", id=1, name="invoice")
        with pytest.raises(FrozenInstanceError):
            obj.name = "receipt"  # type: ignore[misc]

    def test_chunk_hit_is_frozen(self) -> None:
        from store.models import ChunkHit

        obj = ChunkHit(chunk_id=1, document_id=2, text="abc", page_hint=None, score=0.9)
        with pytest.raises(FrozenInstanceError):
            obj.score = 0.5  # type: ignore[misc]

    def test_indexed_document_is_frozen(self) -> None:
        from store.models import IndexedDocument

        obj = IndexedDocument(
            id=1,
            title="Doc",
            correspondent=None,
            document_type=None,
            tags=("a", "b"),
            created=None,
        )
        with pytest.raises(FrozenInstanceError):
            obj.title = "other"  # type: ignore[misc]

    def test_facet_set_is_frozen(self) -> None:
        from store.models import FacetSet

        obj = FacetSet(
            correspondents=(),
            document_types=(),
            tags=(),
            earliest=None,
            latest=None,
        )
        with pytest.raises(FrozenInstanceError):
            obj.earliest = "2024-01-01"  # type: ignore[misc]

    def test_index_stats_is_frozen(self) -> None:
        from store.models import IndexStats

        obj = IndexStats(
            document_count=0,
            chunk_count=0,
            last_reconcile_at=None,
            embedding_model=None,
        )
        with pytest.raises(FrozenInstanceError):
            obj.document_count = 1  # type: ignore[misc]
