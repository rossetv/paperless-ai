"""Tests for appdb.connection — the app-database connection factory.

Covers the connection invariants the rest of appdb relies on: WAL journal
mode (one writer + concurrent readers), enforced foreign keys (so
``ON DELETE CASCADE`` on sessions works), a row factory, a bounded busy
timeout, the ``transaction`` context manager, and — the BLOCKER regression —
that a per-connection-per-thread workload commits every write correctly.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from appdb.connection import connect, transaction
from appdb.schema import ensure_schema
from appdb.users import count_all
from appdb.users import create as create_user


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


# ---------------------------------------------------------------------------
# BLOCKER regression — per-connection-per-thread writes are not corrupted
# ---------------------------------------------------------------------------


def test_concurrent_writers_each_own_connection_lose_no_writes(tmp_path) -> None:
    """N threads, each with its OWN connection, must commit every write intact.

    This is the BLOCKER regression. The Wave 1 backend originally shared ONE
    ``sqlite3.Connection`` across every request thread; ``sqlite3`` connections
    are not safe for concurrent use, so under load writes were silently lost
    and ``cursor.lastrowid`` returned another thread's row id. The fix is one
    connection *per request*. This test models that fix: every thread opens its
    own ``connect()``, inserts a user, commits, and reads the row back by the
    ``create``-reported id. Under the per-connection model every insert must
    survive and every id must resolve to *that thread's* row. Run against a
    single shared connection this fails — lost rows and crossed ``lastrowid``.
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


# ---------------------------------------------------------------------------
# transaction — BEGIN IMMEDIATE context manager
# ---------------------------------------------------------------------------


def test_transaction_commits_on_a_clean_exit(tmp_path) -> None:
    """A clean ``with transaction(conn):`` block commits its writes."""
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
    """An exception inside the block rolls the whole transaction back."""
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
        # The insert before the raise was rolled back — no rows.
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
