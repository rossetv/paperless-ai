"""Tests for appdb migration v3 — the api_keys table.

Covers: a fresh database reaches schema version 3; the api_keys table and
its two indexes exist; the column set matches the spec; the owner_user_id
foreign key cascades on user delete; the key_hash UNIQUE constraint rejects
a duplicate; the migration is idempotent.
"""

from __future__ import annotations

import sqlite3

import pytest

from appdb.connection import connect
from appdb.migrations import run_migrations
from appdb.schema import SCHEMA_VERSION, ensure_schema


@pytest.fixture()
def conn(tmp_path):
    """A fresh, configured app.db connection with no schema applied."""
    c = connect(str(tmp_path / "app.db"))
    yield c
    c.close()


def _table_names(c: sqlite3.Connection) -> set[str]:
    rows = c.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def _index_names(c: sqlite3.Connection) -> set[str]:
    rows = c.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def _schema_version(c: sqlite3.Connection) -> int:
    row = c.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    return int(row[0])


def test_schema_version_constant_is_at_least_three() -> None:
    """The code's declared schema version includes the api_keys migration."""
    assert SCHEMA_VERSION >= 3


def test_fresh_database_reaches_schema_version_three(conn) -> None:
    run_migrations(conn)
    assert _schema_version(conn) == SCHEMA_VERSION
    assert SCHEMA_VERSION >= 3


def test_fresh_database_has_the_api_keys_table(conn) -> None:
    run_migrations(conn)
    assert "api_keys" in _table_names(conn)


def test_api_keys_table_has_the_expected_columns(conn) -> None:
    run_migrations(conn)
    cols = {
        row[1] for row in conn.execute("PRAGMA table_info(api_keys)")
    }
    assert cols == {
        "id",
        "key_hash",
        "key_prefix",
        "name",
        "owner_user_id",
        "scopes",
        "created_at",
        "expires_at",
        "last_used_at",
        "revoked_at",
        "request_count",
    }


def test_api_keys_has_its_indexes(conn) -> None:
    run_migrations(conn)
    indexes = _index_names(conn)
    assert "idx_api_keys_key_hash" in indexes
    assert "idx_api_keys_owner_user_id" in indexes


def test_key_hash_unique_constraint_rejects_a_duplicate(conn) -> None:
    """Two rows cannot share a key_hash — auth looks a key up by it."""
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users "
        "(username, password_hash, role, created_at, updated_at) "
        "VALUES ('owner', 'h', 'admin', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO api_keys "
        "(key_hash, key_prefix, name, owner_user_id, scopes, created_at) "
        "VALUES ('dup-hash', 'sk-pls-aaaa', 'one', 1, 'api', 'now')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO api_keys "
            "(key_hash, key_prefix, name, owner_user_id, scopes, "
            " created_at) "
            "VALUES ('dup-hash', 'sk-pls-bbbb', 'two', 1, 'api', 'now')"
        )


def test_owner_user_id_cascades_on_user_delete(conn) -> None:
    """Deleting a user destroys every api_keys row they own."""
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users "
        "(username, password_hash, role, created_at, updated_at) "
        "VALUES ('owner', 'h', 'admin', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO api_keys "
        "(key_hash, key_prefix, name, owner_user_id, scopes, created_at) "
        "VALUES ('h1', 'sk-pls-aaaa', 'k', 1, 'api', 'now')"
    )
    conn.commit()
    conn.execute("DELETE FROM users WHERE id = 1")
    conn.commit()
    remaining = conn.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
    assert remaining == 0


def test_request_count_defaults_to_zero(conn) -> None:
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users "
        "(username, password_hash, role, created_at, updated_at) "
        "VALUES ('owner', 'h', 'admin', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO api_keys "
        "(key_hash, key_prefix, name, owner_user_id, scopes, created_at) "
        "VALUES ('h1', 'sk-pls-aaaa', 'k', 1, 'api', 'now')"
    )
    conn.commit()
    count = conn.execute(
        "SELECT request_count FROM api_keys WHERE id = 1"
    ).fetchone()[0]
    assert count == 0


def test_migration_v3_is_idempotent(conn) -> None:
    ensure_schema(conn)
    ensure_schema(conn)  # a second run must be a no-op
    assert "api_keys" in _table_names(conn)
    assert _schema_version(conn) == SCHEMA_VERSION
