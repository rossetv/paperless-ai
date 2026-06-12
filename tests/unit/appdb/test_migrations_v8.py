"""Tests for appdb migration v8 — the model_pricing table.

Covers: a fresh database reaches schema version 8; the model_pricing table
exists with the expected columns; model is the primary key (rejects a
duplicate); the migration creates the table empty; the migration is idempotent.
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


def test_schema_version_constant_is_at_least_eight() -> None:
    """The code's declared schema version includes the model_pricing migration."""
    assert SCHEMA_VERSION >= 8


def test_fresh_database_reaches_schema_version_eight(conn) -> None:
    run_migrations(conn)
    assert _schema_version(conn) == SCHEMA_VERSION
    assert SCHEMA_VERSION >= 8


def test_fresh_database_has_the_model_pricing_table(conn) -> None:
    run_migrations(conn)
    assert "model_pricing" in _table_names(conn)


def test_model_pricing_table_has_the_expected_columns(conn) -> None:
    run_migrations(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(model_pricing)")}
    assert cols == {
        "model",
        "input_per_mtok",
        "output_per_mtok",
        "as_of",
        "source",
        "fetched_at",
    }


def test_model_is_the_primary_key_and_rejects_a_duplicate(conn) -> None:
    """model is the primary key — a model name appears at most once."""
    run_migrations(conn)
    conn.execute(
        "INSERT INTO model_pricing "
        "(model, input_per_mtok, output_per_mtok, as_of, source, fetched_at) "
        "VALUES ('gpt-5.5', 5.0, 30.0, '2026-06-10', 'bundled', 'now')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO model_pricing "
            "(model, input_per_mtok, output_per_mtok, as_of, source, fetched_at) "
            "VALUES ('gpt-5.5', 9.9, 9.9, '2026-06-10', 'bundled', 'now')"
        )


def test_migration_creates_the_table_empty(conn) -> None:
    """v8 creates an empty table — the seed lives in code, not the migration."""
    run_migrations(conn)
    count = conn.execute("SELECT COUNT(*) FROM model_pricing").fetchone()[0]
    assert count == 0


def test_migration_v8_is_idempotent(conn) -> None:
    ensure_schema(conn)
    ensure_schema(conn)  # a second run must be a no-op
    assert "model_pricing" in _table_names(conn)
    assert _schema_version(conn) == SCHEMA_VERSION
