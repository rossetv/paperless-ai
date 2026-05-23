"""Tests for appdb.migrations — the forward-only migration runner.

Covers: a fresh database reaches SCHEMA_VERSION; the runner is idempotent;
schema_version is persisted in meta; the users and sessions tables and their
indexes exist after v1; a future schema_version raises AppDbError; a failing
migration rolls back atomically (no partial table, no advanced version).
"""

from __future__ import annotations

import sqlite3

import pytest

from appdb.connection import connect
from appdb.migrations import MIGRATIONS, AppDbError, run_migrations
from appdb.schema import SCHEMA_VERSION


def _schema_version(conn: sqlite3.Connection) -> int | None:
    """Read meta.schema_version, returning None when the row is absent."""
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row[0]) if row is not None else None


def _table_names(conn: sqlite3.Connection) -> set[str]:
    """Return the names of every non-internal table in the database."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    """Return the names of every non-internal index in the database."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


@pytest.fixture()
def conn(tmp_path):
    """A fresh, configured app.db connection with no schema applied."""
    c = connect(str(tmp_path / "app.db"))
    yield c
    c.close()


def test_fresh_database_reaches_schema_version(conn) -> None:
    run_migrations(conn)
    assert _schema_version(conn) == SCHEMA_VERSION


def test_fresh_database_has_the_users_table(conn) -> None:
    run_migrations(conn)
    assert "users" in _table_names(conn)


def test_fresh_database_has_the_sessions_table(conn) -> None:
    run_migrations(conn)
    assert "sessions" in _table_names(conn)


def test_fresh_database_has_the_meta_table(conn) -> None:
    run_migrations(conn)
    assert "meta" in _table_names(conn)


def test_fresh_database_has_the_session_indexes(conn) -> None:
    run_migrations(conn)
    indexes = _index_names(conn)
    assert "idx_sessions_token_hash" in indexes
    assert "idx_sessions_user_id" in indexes
    assert "idx_sessions_expires_at" in indexes


def test_run_migrations_is_idempotent(conn) -> None:
    run_migrations(conn)
    run_migrations(conn)  # must be a no-op
    assert _schema_version(conn) == SCHEMA_VERSION
    assert "users" in _table_names(conn)


def test_migrations_list_is_ordered_and_unique(conn) -> None:
    versions = [v for v, _ in MIGRATIONS]
    assert len(MIGRATIONS) > 0
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)


def test_future_schema_version_raises_appdb_error(conn) -> None:
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '9999')")
    conn.commit()
    with pytest.raises(AppDbError, match="9999"):
        run_migrations(conn)


def test_users_role_check_constraint_rejects_a_bad_role(conn) -> None:
    """The users.role CHECK constraint rejects a value outside the enum."""
    run_migrations(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO users "
            "(username, password_hash, role, created_at, updated_at) "
            "VALUES ('x', 'h', 'superuser', 'now', 'now')"
        )


def test_failing_migration_rolls_back_atomically(conn, monkeypatch) -> None:
    """A migration that raises partway leaves the database wholly unchanged."""

    def _failing(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE partial (x INTEGER)")
        raise RuntimeError("simulated crash")

    monkeypatch.setattr("appdb.migrations.MIGRATIONS", [(1, _failing)])
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_migrations(conn)
    assert "partial" not in _table_names(conn)
    assert _schema_version(conn) is None


def test_migration_v4_creates_the_config_table_during_full_migration(tmp_path) -> None:
    """The config table is present after a full migration chain."""
    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(config)").fetchall()
        }
        assert "key" in columns
        assert "value" in columns
    finally:
        conn.close()


def test_migration_v4_creates_the_config_table(tmp_path) -> None:
    """Migration v4 creates a config table with the expected columns."""
    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(config)").fetchall()
        }
        assert columns == {"key", "value", "updated_at"}
    finally:
        conn.close()


def test_config_key_is_the_primary_key(tmp_path) -> None:
    """The config table rejects a duplicate key — key is the primary key."""
    import sqlite3

    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)",
            ("CHUNK_SIZE", "2000", "2026-05-22T00:00:00+00:00"),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)",
                ("CHUNK_SIZE", "4000", "2026-05-22T00:00:00+00:00"),
            )
    finally:
        conn.close()


def test_config_value_is_not_null(tmp_path) -> None:
    """The config.value column is NOT NULL."""
    import sqlite3

    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)",
                ("CHUNK_SIZE", None, "2026-05-22T00:00:00+00:00"),
            )
    finally:
        conn.close()


def test_migration_v4_seeds_config_version_zero(tmp_path) -> None:
    """Migration v4 seeds a config_version row in meta, starting at 0."""
    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'config_version'"
        ).fetchone()
        assert row is not None, "config_version row was not seeded"
        assert int(row[0]) == 0
    finally:
        conn.close()


def test_migration_v5_brings_schema_version_to_5(tmp_path) -> None:
    """A fresh database migrates all the way to v5."""
    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        version = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        assert int(version) == 5
    finally:
        conn.close()


def test_migration_v5_creates_the_daemon_status_table(tmp_path) -> None:
    """Migration v5 creates daemon_status with the expected columns."""
    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(daemon_status)").fetchall()
        }
        assert columns == {
            "name",
            "detail",
            "processed_count",
            "last_heartbeat",
            "updated_at",
        }
    finally:
        conn.close()


def test_migration_v5_creates_the_reconcile_activity_table(tmp_path) -> None:
    """Migration v5 creates reconcile_activity with the expected columns."""
    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(reconcile_activity)").fetchall()
        }
        assert columns == {
            "id",
            "kind",
            "started_at",
            "finished_at",
            "ok",
            "summary",
            "detail",
        }
    finally:
        conn.close()


def test_daemon_status_name_is_the_primary_key(tmp_path) -> None:
    """daemon_status rejects a duplicate name — name is the primary key."""
    import sqlite3

    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO daemon_status "
            "(name, detail, processed_count, last_heartbeat, updated_at) "
            "VALUES ('ocr', 'idle', 0, ?, ?)",
            ("2026-05-22T00:00:00+00:00", "2026-05-22T00:00:00+00:00"),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO daemon_status "
                "(name, detail, processed_count, last_heartbeat, "
                "updated_at) VALUES ('ocr', 'busy', 1, ?, ?)",
                ("2026-05-22T00:01:00+00:00", "2026-05-22T00:01:00+00:00"),
            )
    finally:
        conn.close()


def test_reconcile_activity_kind_check_rejects_a_bad_kind(tmp_path) -> None:
    """reconcile_activity.kind is CHECK-constrained to sync/sweep."""
    import sqlite3

    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO reconcile_activity "
                "(kind, started_at, finished_at, ok, summary, detail) "
                "VALUES ('explode', ?, ?, 1, '{}', 'x')",
                ("2026-05-22T00:00:00+00:00", "2026-05-22T00:00:01+00:00"),
            )
    finally:
        conn.close()
