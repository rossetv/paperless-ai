"""Tests for appdb.connection: connection pragmas and the transaction manager."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from appdb.connection import connect, transaction
from appdb.schema import ensure_schema
from appdb.users import count_all
from appdb.users import create as create_user


def test_connect_returns_a_connection(tmp_path) -> None:
    conn = connect(str(tmp_path / "app.db"))
    try:
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()


def test_connect_enables_wal_mode(tmp_path) -> None:
    conn = connect(str(tmp_path / "app.db"))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_connect_enables_foreign_keys(tmp_path) -> None:
    """ON DELETE CASCADE on sessions depends on foreign-key enforcement."""
    conn = connect(str(tmp_path / "app.db"))
    try:
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert enabled == 1
    finally:
        conn.close()


def test_connect_sets_a_row_factory(tmp_path) -> None:
    conn = connect(str(tmp_path / "app.db"))
    try:
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_connect_sets_a_busy_timeout(tmp_path) -> None:
    conn = connect(str(tmp_path / "app.db"))
    try:
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout >= 5000
    finally:
        conn.close()


def test_connect_creates_the_database_file(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    conn = connect(str(db_path))
    try:
        assert db_path.exists()
    finally:
        conn.close()


def test_concurrent_writers_each_own_connection_lose_no_writes(tmp_path) -> None:
    """N threads, each with its own connection, must commit every write intact.

    sqlite3 connections are not safe for concurrent use: one shared connection
    loses writes under load and returns another thread's ``lastrowid``.
    """
    db_path = str(tmp_path / "app.db")
    ensure_schema(connect(db_path))

    threads_count = 8
    inserts_per_thread = 25
    failures: list[str] = []
    failures_lock = threading.Lock()
    start = threading.Barrier(threads_count)

    def worker(thread_index: int) -> None:
        # Each thread owns its connection for its whole lifetime — exactly the
        # per-request model search.deps.get_app_db gives the HTTP server.
        conn = connect(db_path)
        try:
            start.wait()
            for insert_index in range(inserts_per_thread):
                username = f"user-{thread_index}-{insert_index}"
                created = create_user(
                    conn,
                    username=username,
                    password_hash="hash",
                    role="member",
                )
                # The id create() reports must resolve back to THIS username —
                # a crossed lastrowid (the shared-connection bug) returns
                # another thread's row here.
                row = conn.execute(
                    "SELECT username FROM users WHERE id = ?", (created.id,)
                ).fetchone()
                if row is None or row["username"] != username:
                    with failures_lock:
                        failures.append(
                            f"id {created.id} for {username!r} resolved to "
                            f"{None if row is None else row['username']!r}"
                        )
        except Exception as exc:  # noqa: BLE001 - record, do not crash the test
            with failures_lock:
                failures.append(f"thread {thread_index}: {exc!r}")
        finally:
            conn.close()

    threads = [
        threading.Thread(target=worker, args=(index,)) for index in range(threads_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not failures, f"per-connection workload corrupted: {failures}"
    # Every single insert was committed and is visible — no silent write loss.
    verifier = connect(db_path)
    try:
        assert count_all(verifier) == threads_count * inserts_per_thread
    finally:
        verifier.close()


def test_transaction_commits_on_a_clean_exit(tmp_path) -> None:
    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        with transaction(conn):
            conn.execute(
                "INSERT INTO users "
                "(username, password_hash, role, status, created_at, updated_at) "
                "VALUES ('t', 'h', 'member', 'active', 'now', 'now')"
            )
        assert count_all(conn) == 1
    finally:
        conn.close()


def test_transaction_rolls_back_on_an_exception(tmp_path) -> None:
    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        with pytest.raises(RuntimeError, match="boom"):
            with transaction(conn):
                conn.execute(
                    "INSERT INTO users "
                    "(username, password_hash, role, status, created_at, "
                    " updated_at) "
                    "VALUES ('t', 'h', 'member', 'active', 'now', 'now')"
                )
                raise RuntimeError("boom")
        assert count_all(conn) == 0
    finally:
        conn.close()


def test_transaction_tolerates_a_committing_callee(tmp_path) -> None:
    """A block whose callee commits (appdb writers do) still exits cleanly.

    ``appdb.users.create`` commits internally; calling it inside
    ``transaction`` must not raise a "cannot commit - no transaction" error —
    the manager skips its own commit when the transaction is already closed.
    """
    conn = connect(str(tmp_path / "app.db"))
    try:
        ensure_schema(conn)
        with transaction(conn):
            create_user(conn, username="t", password_hash="h", role="member")
        assert count_all(conn) == 1
    finally:
        conn.close()
