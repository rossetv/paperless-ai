"""Tests for appdb.connection — the app-database connection factory.

Covers the connection invariants the rest of appdb relies on: WAL journal
mode (one writer + concurrent readers), enforced foreign keys (so
``ON DELETE CASCADE`` on sessions works), a row factory, and a bounded busy
timeout.
"""

from __future__ import annotations

import sqlite3

from appdb.connection import connect


def test_connect_returns_a_connection(tmp_path) -> None:
    """connect() yields an open sqlite3 connection."""
    conn = connect(str(tmp_path / "app.db"))
    try:
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()


def test_connect_enables_wal_mode(tmp_path) -> None:
    """The connection runs in WAL journal mode."""
    conn = connect(str(tmp_path / "app.db"))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_connect_enables_foreign_keys(tmp_path) -> None:
    """Foreign-key enforcement is on, so ON DELETE CASCADE is active."""
    conn = connect(str(tmp_path / "app.db"))
    try:
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert enabled == 1
    finally:
        conn.close()


def test_connect_sets_a_row_factory(tmp_path) -> None:
    """Rows come back as sqlite3.Row so callers index by column name."""
    conn = connect(str(tmp_path / "app.db"))
    try:
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_connect_sets_a_busy_timeout(tmp_path) -> None:
    """A non-zero busy timeout avoids indefinite hangs on a write lock."""
    conn = connect(str(tmp_path / "app.db"))
    try:
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout >= 5000
    finally:
        conn.close()


def test_connect_creates_the_database_file(tmp_path) -> None:
    """Opening a fresh path creates the database file on disk."""
    db_path = tmp_path / "app.db"
    conn = connect(str(db_path))
    try:
        assert db_path.exists()
    finally:
        conn.close()
