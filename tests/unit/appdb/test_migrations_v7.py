"""Tests for appdb migration v7 — the api_key_usage table.

Covers: a fresh database reaches schema version 7; the api_key_usage table
exists with the expected columns; the composite (api_key_id, usage_date)
primary key rejects a duplicate; the api_key_id foreign key cascades on key
delete; tokens and calls default to 0; the migration is idempotent.
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


def _schema_version(c: sqlite3.Connection) -> int:
    row = c.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row[0])


def _seed_key(c: sqlite3.Connection, api_key_id: int = 7) -> None:
    """Insert a user and an api_keys row the usage rows can reference."""
    c.execute(
        "INSERT OR IGNORE INTO users "
        "(id, username, password_hash, role, created_at, updated_at) "
        "VALUES (1, 'u', 'h', 'member', 'now', 'now')"
    )
    c.execute(
        "INSERT INTO api_keys "
        "(id, key_hash, key_prefix, name, owner_user_id, scopes, created_at) "
        "VALUES (?, ?, 'sk-pls', 'k', 1, 'api', 'now')",
        (api_key_id, f"hash{api_key_id}"),
    )
    c.commit()


def test_schema_version_constant_is_at_least_seven() -> None:
    """The code's declared schema version includes the api_key_usage migration."""
    assert SCHEMA_VERSION >= 7


def test_fresh_database_reaches_schema_version_seven(conn) -> None:
    run_migrations(conn)
    assert _schema_version(conn) == SCHEMA_VERSION
    assert SCHEMA_VERSION >= 7


def test_fresh_database_has_the_api_key_usage_table(conn) -> None:
    run_migrations(conn)
    assert "api_key_usage" in _table_names(conn)


def test_api_key_usage_table_has_the_expected_columns(conn) -> None:
    run_migrations(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(api_key_usage)")}
    assert cols == {"api_key_id", "usage_date", "tokens", "calls"}


def test_composite_primary_key_rejects_a_duplicate(conn) -> None:
    """(api_key_id, usage_date) is the primary key — one bucket per key per day."""
    run_migrations(conn)
    _seed_key(conn)
    conn.execute(
        "INSERT INTO api_key_usage (api_key_id, usage_date, tokens, calls) "
        "VALUES (7, '2026-06-12', 10, 1)"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO api_key_usage (api_key_id, usage_date, tokens, calls) "
            "VALUES (7, '2026-06-12', 20, 1)"
        )


def test_tokens_and_calls_default_to_zero(conn) -> None:
    run_migrations(conn)
    _seed_key(conn)
    conn.execute(
        "INSERT INTO api_key_usage (api_key_id, usage_date) VALUES (7, '2026-06-12')"
    )
    conn.commit()
    row = conn.execute(
        "SELECT tokens, calls FROM api_key_usage WHERE api_key_id = 7"
    ).fetchone()
    assert (row["tokens"], row["calls"]) == (0, 0)


def test_api_key_id_cascades_on_key_delete(conn) -> None:
    """Deleting an api_keys row destroys every usage row it owns."""
    run_migrations(conn)
    _seed_key(conn)
    conn.execute(
        "INSERT INTO api_key_usage (api_key_id, usage_date, tokens, calls) "
        "VALUES (7, '2026-06-12', 50, 1)"
    )
    conn.commit()
    conn.execute("DELETE FROM api_keys WHERE id = 7")
    conn.commit()
    remaining = conn.execute("SELECT COUNT(*) FROM api_key_usage").fetchone()[0]
    assert remaining == 0


def test_migration_v7_is_idempotent(conn) -> None:
    ensure_schema(conn)
    ensure_schema(conn)  # a second run must be a no-op
    assert "api_key_usage" in _table_names(conn)
    assert _schema_version(conn) == SCHEMA_VERSION
