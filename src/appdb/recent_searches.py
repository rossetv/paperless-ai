"""Per-user recent-search history, the ``recent_searches`` table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import structlog

from appdb.connection import utc_now_iso

log = structlog.get_logger(__name__)

# The search UI shows a short strip, so a deeper history would never be read.
MAX_PER_USER = 20


@dataclass(frozen=True, slots=True)
class RecentSearch:
    """One row of the ``recent_searches`` table."""

    id: int
    user_id: int
    query: str
    created_at: str


def _row_to_recent_search(row: sqlite3.Row) -> RecentSearch:
    """Build a :class:`RecentSearch` from a ``recent_searches`` table row."""
    return RecentSearch(
        id=row["id"],
        user_id=row["user_id"],
        query=row["query"],
        created_at=row["created_at"],
    )


def record(conn: sqlite3.Connection, *, user_id: int, query: str) -> RecentSearch:
    """Record one search for *user_id* and return the stored row.

    An identical earlier query is deleted first, so repeating a query moves it
    to the top, and the history is then trimmed to :data:`MAX_PER_USER`. All
    three steps share one transaction so a reader never sees it mid-trim.
    """
    now = utc_now_iso()
    with conn:
        conn.execute(
            "DELETE FROM recent_searches WHERE user_id = ? AND query = ?",
            (user_id, query),
        )
        cursor = conn.execute(
            "INSERT INTO recent_searches (user_id, query, created_at) VALUES (?, ?, ?)",
            (user_id, query, now),
        )
        new_id = int(cursor.lastrowid or 0)
        _trim_to_cap(conn, user_id)
    log.info("appdb.recent_search_recorded", user_id=user_id)
    return RecentSearch(id=new_id, user_id=user_id, query=query, created_at=now)


def _trim_to_cap(conn: sqlite3.Connection, user_id: int) -> None:
    """Delete the user's recent searches beyond the newest :data:`MAX_PER_USER`.

    Does not commit; :func:`record` calls it inside its transaction.
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
    conn: sqlite3.Connection, user_id: int, *, limit: int = MAX_PER_USER
) -> list[RecentSearch]:
    """Return *user_id*'s recent searches, newest first."""
    rows = conn.execute(
        "SELECT id, user_id, query, created_at FROM recent_searches "
        "WHERE user_id = ? "
        "ORDER BY created_at DESC, id DESC "
        "LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [_row_to_recent_search(row) for row in rows]
