"""Per-user recent-search history in the application database.

This module owns the :class:`RecentSearch` dataclass and the typed query
functions over the ``recent_searches`` table (web-redesign §5, app.db
migration v2). Higher layers — the search server's ``POST /api/search`` hook
and its ``GET /api/recent-searches`` handler — call these functions and never
write SQL themselves; ``appdb`` is the only place ``app.db`` SQL is built.

Two behaviours worth stating:

- **De-duplication.** :func:`record` first deletes any existing rows for the
  same user whose ``query`` matches exactly, so re-running an identical query
  moves it to the top of the list rather than stacking a duplicate.
- **Bounded history.** After every insert :func:`record` trims the user's
  history to the :data:`MAX_PER_USER` newest rows, so the table cannot grow
  without bound for a heavy user.

Allowed deps: sqlite3, structlog. Forbidden: store, search, daemon packages,
FastAPI.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

log = structlog.get_logger(__name__)

# The maximum number of recent searches kept per user. record() trims the
# history to this many newest rows after every insert; the search UI shows a
# short strip, so a deeper history would never be read.
MAX_PER_USER = 20

# The default page size for list_for_user — the same as the per-user cap, so
# an unqualified list returns a user's whole retained history.
_DEFAULT_LIMIT = 20


@dataclass(frozen=True, slots=True)
class RecentSearch:
    """One row of the ``recent_searches`` table — a single recorded search.

    Frozen: a loaded row is a snapshot, never mutated in place.

    Attributes:
        id: The integer primary key.
        user_id: The id of the user who ran the search.
        query: The verbatim search query text.
        created_at: ISO-8601 UTC timestamp of when the search was recorded.
    """

    id: int
    user_id: int
    query: str
    created_at: str


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``+00:00``
    offset — the timestamp format the ``recent_searches`` table stores."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_recent_search(row: sqlite3.Row) -> RecentSearch:
    """Build a :class:`RecentSearch` from a ``recent_searches`` table row."""
    return RecentSearch(
        id=row["id"],
        user_id=row["user_id"],
        query=row["query"],
        created_at=row["created_at"],
    )


def record(
    conn: sqlite3.Connection, *, user_id: int, query: str
) -> RecentSearch:
    """Record one search for *user_id* and return the stored row.

    De-duplicates first: any existing rows for this user whose ``query``
    matches *query* exactly are deleted, so repeating a query promotes it to
    the top of the list. After inserting, the user's history is trimmed to
    the :data:`MAX_PER_USER` newest rows.

    The delete, insert and trim run inside one transaction so a concurrent
    reader never sees the history mid-trim.

    Args:
        conn: An open, migrated ``app.db`` connection.
        user_id: The id of the user who ran the search.
        query: The verbatim search query text.

    Returns:
        The inserted :class:`RecentSearch`.
    """
    now = _utc_now_iso()
    # Remove any prior identical query for this user so the new row is the
    # single, newest occurrence.
    conn.execute(
        "DELETE FROM recent_searches WHERE user_id = ? AND query = ?",
        (user_id, query),
    )
    cursor = conn.execute(
        "INSERT INTO recent_searches (user_id, query, created_at) "
        "VALUES (?, ?, ?)",
        (user_id, query, now),
    )
    new_id = int(cursor.lastrowid or 0)
    _trim_to_cap(conn, user_id)
    conn.commit()
    log.info("appdb.recent_search_recorded", user_id=user_id)
    return RecentSearch(
        id=new_id, user_id=user_id, query=query, created_at=now
    )


def _trim_to_cap(conn: sqlite3.Connection, user_id: int) -> None:
    """Delete the user's recent searches beyond the newest :data:`MAX_PER_USER`.

    Keeps the ``MAX_PER_USER`` rows with the most recent ``created_at`` (id
    breaks a tie deterministically) and deletes the rest. Called by
    :func:`record` inside its transaction; the caller commits.

    Args:
        conn: An open ``app.db`` connection.
        user_id: The user whose history is being trimmed.
    """
    conn.execute(
        "DELETE FROM recent_searches "
        "WHERE user_id = ? AND id NOT IN ("
        "    SELECT id FROM recent_searches "
        "    WHERE user_id = ? "
        "    ORDER BY created_at DESC, id DESC "
        "    LIMIT ?"
        ")",
        (user_id, user_id, MAX_PER_USER),
    )


def list_for_user(
    conn: sqlite3.Connection, user_id: int, *, limit: int = _DEFAULT_LIMIT
) -> list[RecentSearch]:
    """Return *user_id*'s recent searches, newest first.

    Args:
        conn: An open, migrated ``app.db`` connection.
        user_id: The user whose history to read.
        limit: The maximum number of rows to return; defaults to
            :data:`MAX_PER_USER`.

    Returns:
        The user's recent searches as :class:`RecentSearch` objects, ordered
        most-recent first. An empty list when the user has no history.
    """
    rows = conn.execute(
        "SELECT id, user_id, query, created_at FROM recent_searches "
        "WHERE user_id = ? "
        "ORDER BY created_at DESC, id DESC "
        "LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [_row_to_recent_search(row) for row in rows]
