"""SQLite connection factory for the application database (``app.db``).

``connect`` opens a connection configured exactly as every appdb caller
expects: WAL journal mode (one writer plus concurrent readers across
processes — Wave 4's daemons read this same database), ``foreign_keys = ON``
so the ``sessions`` table's ``ON DELETE CASCADE`` to ``users`` is honoured, a
``sqlite3.Row`` row factory so query code indexes columns by name, and a
bounded ``busy_timeout`` so a contended write never hangs indefinitely.

This is adapted from ``store.schema.connect`` — appdb deliberately does not
share code with ``store`` (see the package docstring) — and drops the
sqlite-vec extension load, which ``app.db`` does not need.

Allowed deps: sqlite3. Forbidden: any import from store/search/daemons.
"""

from __future__ import annotations

import sqlite3

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
    # check_same_thread=False: the search server serves requests on a thread
    # pool (FastAPI's run_in_executor), so the connection is touched from more
    # than one thread. appdb query code serialises writes with its own lock.
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
