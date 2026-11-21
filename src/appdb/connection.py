"""Connection factory, transaction helper and shared helpers for ``app.db``."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone


class RowVanishedError(Exception):
    """A row this process just wrote is unexpectedly absent from its own write.

    Raised when a single-row ``INSERT`` succeeds but ``cursor.lastrowid`` is
    ``None``, or the row read back right after it is missing. Either breaks an
    invariant SQLite guarantees, so the caller cannot recover.
    """


# A contended write waits this long for the lock, then raises OperationalError.
_BUSY_TIMEOUT_MS = 5000


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``+00:00`` offset.

    Every ``app.db`` timestamp uses this format, so they compare as strings.
    """
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: str) -> sqlite3.Connection:
    """Open an ``app.db`` connection: WAL, foreign keys on, ``Row`` factory.

    The file is created if its parent directory exists.
    """
    # check_same_thread=False: the search server opens one connection per
    # request (search.deps.get_app_db), and FastAPI's threadpool may hop it
    # between threads, though never concurrently. The flag is only safe because
    # a connection is never shared between requests.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # The daemons read this database while the search server writes it.
    conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL durability is safe under WAL: a crash can lose the last
    # checkpoint but never corrupts a committed transaction.
    conn.execute("PRAGMA synchronous=NORMAL")
    # Needed for the ON DELETE CASCADE foreign keys to fire.
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")

    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Run a block inside a ``BEGIN IMMEDIATE`` transaction on *conn*.

    Taking the write lock up front makes a read-then-write check (e.g. "count
    the admins, then demote one") atomic against a racing request. Commits on a
    clean exit and rolls back on any exception, ``KeyboardInterrupt`` included.
    If a helper inside the block already committed, the final commit is skipped.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    if conn.in_transaction:
        conn.commit()
