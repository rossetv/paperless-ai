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
    conn.execute(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', '9999')"
    )
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
