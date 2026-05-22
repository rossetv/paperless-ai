"""Tests for app.db migration v2 — the recent_searches table.

Covers: a fresh database now reaches schema version 2; the recent_searches
table and its (user_id, created_at) index exist after the migration; the
user_id foreign key is declared with ON DELETE CASCADE; the NOT NULL
constraints on user_id and query are enforced; and migrating an
already-v1 database forward adds the table without disturbing v1 data.
"""

from __future__ import annotations

import sqlite3

import pytest

from appdb.connection import connect
from appdb.migrations import run_migrations
from appdb.schema import SCHEMA_VERSION


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


def test_schema_version_constant_is_two() -> None:
    """SCHEMA_VERSION advanced to 2 — migration v2 is the new head."""
    assert SCHEMA_VERSION == 2


def test_fresh_database_reaches_schema_version_two(conn) -> None:
    run_migrations(conn)
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    assert int(row[0]) == 2


def test_fresh_database_has_the_recent_searches_table(conn) -> None:
    run_migrations(conn)
    assert "recent_searches" in _table_names(conn)


def test_fresh_database_has_the_recent_searches_index(conn) -> None:
    run_migrations(conn)
    assert "idx_recent_searches_user_created" in _index_names(conn)


def test_recent_searches_user_id_cascades_on_user_delete(conn) -> None:
    """Deleting a user removes their recent_searches rows (ON DELETE CASCADE)."""
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users "
        "(id, username, password_hash, role, created_at, updated_at) "
        "VALUES (1, 'u', 'h', 'member', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO recent_searches (user_id, query, created_at) "
        "VALUES (1, 'gas bill', 'now')"
    )
    conn.commit()
    conn.execute("DELETE FROM users WHERE id = 1")
    conn.commit()
    remaining = conn.execute(
        "SELECT COUNT(*) FROM recent_searches"
    ).fetchone()[0]
    assert remaining == 0


def test_recent_searches_query_is_not_null(conn) -> None:
    """The query column rejects a NULL value."""
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users "
        "(id, username, password_hash, role, created_at, updated_at) "
        "VALUES (1, 'u', 'h', 'member', 'now', 'now')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO recent_searches (user_id, query, created_at) "
            "VALUES (1, NULL, 'now')"
        )


def test_recent_searches_user_id_is_not_null(conn) -> None:
    """The user_id column rejects a NULL value."""
    run_migrations(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO recent_searches (user_id, query, created_at) "
            "VALUES (NULL, 'q', 'now')"
        )


def test_v1_database_migrates_forward_keeping_users(conn) -> None:
    """A database stopped at v1 migrates to v2 without losing v1 rows."""
    # Apply only v1 by pinning MIGRATIONS to the v1 entry.
    import appdb.migrations as migrations_module

    v1_only = [migrations_module.MIGRATIONS[0]]
    original = migrations_module.MIGRATIONS
    migrations_module.MIGRATIONS = v1_only
    try:
        run_migrations(conn)
    finally:
        migrations_module.MIGRATIONS = original
    conn.execute(
        "INSERT INTO users "
        "(id, username, password_hash, role, created_at, updated_at) "
        "VALUES (7, 'kept', 'h', 'admin', 'now', 'now')"
    )
    conn.commit()
    assert "recent_searches" not in _table_names(conn)

    # Now run the full migration list — v2 should apply on top.
    run_migrations(conn)
    assert "recent_searches" in _table_names(conn)
    kept = conn.execute(
        "SELECT username FROM users WHERE id = 7"
    ).fetchone()
    assert kept["username"] == "kept"
