"""SQLite connection factory for the application database (``app.db``).

``connect`` opens a connection configured exactly as every appdb caller
expects: WAL journal mode (one writer plus concurrent readers across
processes — Wave 4's daemons read this same database), ``foreign_keys = ON``
so the ``sessions`` table's ``ON DELETE CASCADE`` to ``users`` is honoured, a
``sqlite3.Row`` row factory so query code indexes columns by name, and a
bounded ``busy_timeout`` so a contended write never hangs indefinitely.

``transaction`` is the explicit-transaction context manager: it opens a
``BEGIN IMMEDIATE`` (taking SQLite's write lock up front), commits on a clean
exit, and rolls back on any exception. The search server's last-admin guards
use it to make a read-then-write check atomic.

This is adapted from ``store.schema.connect`` — appdb deliberately does not
share code with ``store`` (see the package docstring) — and drops the
sqlite-vec extension load, which ``app.db`` does not need.

Allowed deps: sqlite3. Forbidden: any import from store/search/daemons.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

# The busy timeout, in milliseconds. A contended write waits up to this long
# for the lock before raising sqlite3.OperationalError, rather than hanging.
_BUSY_TIMEOUT_MS = 5000


def connect(db_path: str) -> sqlite3.Connection:
    """Open and configure a connection to the application database.

    Args:
        db_path: Filesystem path to the ``app.db`` SQLite file. The file and
            its parent directory must already be reachable; ``sqlite3.connect``
            creates the file itself if the directory exists.

    Returns:
        An open :class:`sqlite3.Connection` with WAL mode, enforced foreign
        keys, a :class:`sqlite3.Row` row factory, and a bounded busy timeout.
    """
    # check_same_thread=False: the search server opens ONE connection per HTTP
    # request (see search.deps.get_app_db) and uses it strictly sequentially
    # within that request. FastAPI runs synchronous dependencies and handlers
    # in the anyio threadpool, so a single request's connection may be touched
    # from more than one threadpool thread — but only ever one at a time, never
    # concurrently. Disabling the same-thread guard permits that legitimate
    # sequential thread hop. It does NOT make concurrent use of one connection
    # safe: under the previous shared-connection model (one connection on
    # app.state for every request) check_same_thread=False silenced the guard
    # while N request threads drove the same connection at once — a latent data
    # corruption bug. The per-request model is what makes this flag correct.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # WAL: one writer plus concurrent readers, across processes — required
    # because Wave 4's daemons read this database while the search server
    # writes it.
    conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL durability is safe under WAL: a crash can lose the last
    # checkpoint but never corrupts a committed transaction.
    conn.execute("PRAGMA synchronous=NORMAL")
    # Enforce FK constraints so sessions.user_id ON DELETE CASCADE fires.
    conn.execute("PRAGMA foreign_keys=ON")
    # Bound the wait for a contended write lock instead of hanging forever.
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")

    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Run a block inside a ``BEGIN IMMEDIATE`` transaction on *conn*.

    ``BEGIN IMMEDIATE`` acquires SQLite's write lock at the start of the block
    rather than lazily on the first write, so a concurrent writer blocks (up to
    ``busy_timeout``) at *its* ``BEGIN IMMEDIATE`` until this block commits and
    then observes this transaction's committed effect. That is what makes a
    read-then-write check (e.g. "count the admins, then demote one") atomic
    against a racing request.

    On a clean exit the transaction is committed; on any exception (including
    :class:`BaseException`, so a ``KeyboardInterrupt`` mid-block does not leave
    the lock held) it is rolled back. A block may call a helper that itself
    commits — several :mod:`appdb.users` writers do — in which case the
    transaction is already closed by the time control returns here; the final
    commit is skipped (guarded on :attr:`sqlite3.Connection.in_transaction`),
    so composing this manager with an auto-committing writer is correct and the
    whole guard-then-write sequence is still one ``BEGIN IMMEDIATE``
    transaction.

    Args:
        conn: An open ``app.db`` connection.

    Yields:
        Nothing — the block runs its statements directly on *conn*.
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
