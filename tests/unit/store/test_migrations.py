"""Tests for store.migrations — the versioned migration runner.

Covers:
- A fresh database ends at SCHEMA_VERSION after run_migrations()
- run_migrations() is idempotent (calling it twice is a no-op)
- schema_version is persisted in the meta table
- A database whose meta.schema_version is higher than any known migration
  raises StoreError (future-version guard)
"""

from __future__ import annotations

import sqlite3
import unittest.mock as _mock

import pytest

from store.migrations import MIGRATIONS, StoreError, run_migrations
from store.schema import SCHEMA_VERSION, connect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_schema_version(conn: sqlite3.Connection) -> int | None:
    """Read schema_version from meta, returning None if the row is absent."""
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        # meta table does not exist yet
        return None
    return int(row[0]) if row is not None else None


def _table_names(conn: sqlite3.Connection) -> set[str]:
    """Return names of all non-internal tables (real + virtual) in the DB."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow') AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    """Return the names of all indexes in the DB."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()
    return {row[0] for row in rows}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    """A fresh, configured connection with no schema applied."""
    db_path = str(tmp_path / "migrations_test.db")
    c = connect(db_path)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Fresh database reaches SCHEMA_VERSION
# ---------------------------------------------------------------------------


class TestFreshDatabase:
    """run_migrations() on a blank database applies all migrations correctly."""

    def test_fresh_database_ends_at_schema_version(self, conn) -> None:
        run_migrations(conn)
        version = _get_schema_version(conn)
        assert version == SCHEMA_VERSION

    def test_fresh_database_has_documents_table(self, conn) -> None:
        run_migrations(conn)
        assert "documents" in _table_names(conn)

    def test_fresh_database_has_chunks_table(self, conn) -> None:
        run_migrations(conn)
        assert "chunks" in _table_names(conn)

    def test_fresh_database_has_meta_table(self, conn) -> None:
        run_migrations(conn)
        assert "meta" in _table_names(conn)

    def test_fresh_database_has_taxonomy_table(self, conn) -> None:
        run_migrations(conn)
        assert "taxonomy" in _table_names(conn)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """run_migrations() is safe to call on an already-migrated database."""

    def test_run_migrations_twice_does_not_raise(self, conn) -> None:
        run_migrations(conn)
        run_migrations(conn)  # must be a no-op

    def test_run_migrations_twice_schema_version_unchanged(self, conn) -> None:
        run_migrations(conn)
        run_migrations(conn)
        assert _get_schema_version(conn) == SCHEMA_VERSION

    def test_run_migrations_twice_tables_still_present(self, conn) -> None:
        run_migrations(conn)
        run_migrations(conn)
        assert "documents" in _table_names(conn)


# ---------------------------------------------------------------------------
# schema_version persisted in meta
# ---------------------------------------------------------------------------


class TestSchemaVersionPersisted:
    """schema_version is written to the meta table after each migration."""

    def test_schema_version_row_present_after_migration(self, conn) -> None:
        run_migrations(conn)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        assert row is not None

    def test_schema_version_value_matches_constant(self, conn) -> None:
        run_migrations(conn)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        assert int(row[0]) == SCHEMA_VERSION

    def test_migrations_list_is_ordered_and_non_empty(self) -> None:
        """MIGRATIONS must be a non-empty list with strictly ascending versions."""
        assert len(MIGRATIONS) > 0
        versions = [v for v, _ in MIGRATIONS]
        assert versions == sorted(versions)
        assert len(set(versions)) == len(versions), "duplicate migration version"


# ---------------------------------------------------------------------------
# Migration atomicity
# ---------------------------------------------------------------------------


class TestMigrationAtomicity:
    """A migration's DDL and its schema_version write commit or roll back as one.

    run_migrations() wraps each migration in an explicit BEGIN…COMMIT
    transaction (rolling back on any failure). This guards two regressions:
    conn.executescript() issuing an implicit COMMIT before executing, and a
    bare ``with conn:`` failing to open a transaction at all so DDL would
    autocommit individually.
    """

    def test_failed_migration_rolls_back_completely(self, conn, monkeypatch) -> None:
        """A migration that fails partway leaves the database wholly unchanged.

        Injects a migration that creates a table and then raises, mimicking a
        crash mid-migration. Afterwards neither the partial table nor an
        advanced schema_version may survive — proving the whole migration is
        one atomic transaction.
        """

        def _failing_migration(c: sqlite3.Connection) -> None:
            c.execute("CREATE TABLE partial_migration_table (x INTEGER)")
            raise RuntimeError("simulated crash mid-migration")

        monkeypatch.setattr("store.migrations.MIGRATIONS", [(1, _failing_migration)])
        with pytest.raises(RuntimeError, match="simulated crash"):
            run_migrations(conn)

        # The partial table must have been rolled back ...
        assert "partial_migration_table" not in _table_names(conn)
        # ... and schema_version must not have advanced (meta never created).
        assert _get_schema_version(conn) is None

    def test_schema_version_written_in_same_transaction_as_ddl(self, conn) -> None:
        """After run_migrations, both the tables and schema_version exist.

        The happy-path consistency check: the schema and the schema_version
        row are both present and consistent after a successful run. The
        crash/rollback path is covered by
        test_failed_migration_rolls_back_completely.
        """
        run_migrations(conn)
        version = _get_schema_version(conn)
        tables = _table_names(conn)
        assert version == SCHEMA_VERSION
        assert "documents" in tables
        assert "chunks" in tables
        assert "meta" in tables

    def test_v1_migration_uses_execute_not_executescript(self) -> None:
        """_migrate_v1 must not call conn.executescript() on the connection.

        executescript() issues an implicit COMMIT before executing, which breaks
        the atomicity of the surrounding ``with conn:`` transaction.  The fix
        is to call conn.execute() for each statement; this test verifies that
        executescript is not called on the connection during migration.
        """
        import unittest.mock as _mock
        from store.migrations import _migrate_v1

        mock_conn = _mock.MagicMock(spec=sqlite3.Connection)
        # execute() must be called at least once (one per DDL statement).
        _migrate_v1(mock_conn)
        mock_conn.executescript.assert_not_called()
        assert mock_conn.execute.call_count >= 1, (
            "_migrate_v1 must use execute() for each DDL statement"
        )


# ---------------------------------------------------------------------------
# v2: idx_documents_indexed_at
# ---------------------------------------------------------------------------


class TestV2IndexedAtMigration:
    """Migration v2 adds idx_documents_indexed_at to a pre-v2 database."""

    def test_fresh_database_has_indexed_at_index(self, conn) -> None:
        run_migrations(conn)
        assert "idx_documents_indexed_at" in _index_names(conn)

    def test_existing_v1_database_gains_the_index_on_upgrade(self, conn) -> None:
        """A database created at v1 (no indexed_at index) gains it at v2.

        Simulates a deployed v1 database: build the schema, drop the v2 index,
        and roll schema_version back to 1. Re-running migrations must apply v2
        and create the index — the realistic in-place upgrade path.
        """
        run_migrations(conn)
        conn.execute("DROP INDEX IF EXISTS idx_documents_indexed_at")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '1')"
        )
        conn.commit()
        assert "idx_documents_indexed_at" not in _index_names(conn)

        run_migrations(conn)

        assert _get_schema_version(conn) == 2
        assert "idx_documents_indexed_at" in _index_names(conn)


# ---------------------------------------------------------------------------
# Future-version guard
# ---------------------------------------------------------------------------


class TestFutureVersionGuard:
    """A database written by a newer code version raises StoreError."""

    def test_future_schema_version_raises_store_error(self, conn) -> None:
        # Bootstrap the meta table so we can write a version directly.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            INSERT OR REPLACE INTO meta (key, value)
            VALUES ('schema_version', '9999');
            """
        )
        with pytest.raises(StoreError):
            run_migrations(conn)

    def test_store_error_message_is_informative(self, conn) -> None:
        """StoreError message should mention the version numbers involved."""
        future_version = 9999
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            INSERT OR REPLACE INTO meta (key, value)
            VALUES ('schema_version', '{future_version}');
            """
        )
        with pytest.raises(StoreError, match=str(future_version)):
            run_migrations(conn)

    def test_store_error_is_exception_subclass(self) -> None:
        assert issubclass(StoreError, Exception)


# ---------------------------------------------------------------------------
# Corrupt / locked database is not masked as fresh
# ---------------------------------------------------------------------------


class TestCorruptDatabaseFailsLoud:
    """_read_schema_version must only treat a missing meta table as version 0.

    A genuine "no such table: meta" means a fresh database and is correctly
    read as version 0. Any other OperationalError — a malformed disk image, a
    locked file — must propagate rather than be swallowed as "fresh", which
    would re-run every migration against a corrupt or busy database and mask
    the damage (CODE_GUIDELINES.md §1.11 fail-loud).
    """

    def test_missing_meta_table_is_read_as_version_zero(self) -> None:
        from store.migrations import _read_schema_version

        mock_conn = _mock.MagicMock(spec=sqlite3.Connection)
        mock_conn.execute.side_effect = sqlite3.OperationalError("no such table: meta")

        assert _read_schema_version(mock_conn) == 0

    def test_corrupt_database_operational_error_propagates(self) -> None:
        from store.migrations import _read_schema_version

        mock_conn = _mock.MagicMock(spec=sqlite3.Connection)
        mock_conn.execute.side_effect = sqlite3.OperationalError(
            "database disk image is malformed"
        )

        with pytest.raises(sqlite3.OperationalError, match="malformed"):
            _read_schema_version(mock_conn)

    def test_run_migrations_does_not_mask_a_corrupt_database(self) -> None:
        """A corrupt database must not be silently re-migrated from v1."""
        mock_conn = _mock.MagicMock(spec=sqlite3.Connection)
        mock_conn.execute.side_effect = sqlite3.OperationalError(
            "database disk image is malformed"
        )

        with pytest.raises(sqlite3.OperationalError, match="malformed"):
            run_migrations(mock_conn)
