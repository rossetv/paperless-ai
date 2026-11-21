"""Server-side sessions, the ``sessions`` table.

Server-side so that suspending or deleting a user revokes access instantly. Only
``sha256(token)`` is stored, so a database leak yields no usable session; the
caller does the hashing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import structlog

from appdb.connection import RowVanishedError, utc_now_iso

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Session:
    """One row of the ``sessions`` table.

    ``user_agent`` and ``ip`` come from the request that created the session.
    """

    id: int
    token_hash: str
    user_id: int
    created_at: str
    expires_at: str
    last_seen_at: str
    user_agent: str | None
    ip: str | None


def _row_to_session(row: sqlite3.Row) -> Session:
    """Build a :class:`Session` from a ``sessions`` table row."""
    return Session(
        id=row["id"],
        token_hash=row["token_hash"],
        user_id=row["user_id"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        last_seen_at=row["last_seen_at"],
        user_agent=row["user_agent"],
        ip=row["ip"],
    )


_SESSION_COLUMNS = (
    "id, token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip"
)


def create(
    conn: sqlite3.Connection,
    *,
    token_hash: str,
    user_id: int,
    expires_at: str,
    user_agent: str | None = None,
    ip: str | None = None,
) -> Session:
    """Insert a new session and return it fully populated."""
    now = utc_now_iso()
    with conn:
        cursor = conn.execute(
            "INSERT INTO sessions "
            "(token_hash, user_id, created_at, expires_at, last_seen_at, "
            " user_agent, ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token_hash, user_id, now, expires_at, now, user_agent, ip),
        )
    log.info("appdb.session_created", session_id=cursor.lastrowid, user_id=user_id)
    row = conn.execute(
        f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE id = ?",  # nosec B608 - _SESSION_COLUMNS is a module constant; lastrowid bound via ?
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:
        raise RowVanishedError(
            f"session {cursor.lastrowid} missing immediately after INSERT"
        )
    return _row_to_session(row)


def get_by_token_hash(conn: sqlite3.Connection, token_hash: str) -> Session | None:
    """Return the session whose ``token_hash`` matches, or ``None``.

    Expired rows are returned too, so the caller can both reject the request
    and prune the row.
    """
    row = conn.execute(
        f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE token_hash = ?",  # nosec B608 - _SESSION_COLUMNS is a module constant; token_hash bound via ?
        (token_hash,),
    ).fetchone()
    return _row_to_session(row) if row is not None else None


def touch_last_seen(conn: sqlite3.Connection, token_hash: str, *, seen_at: str) -> None:
    """Set ``last_seen_at`` for the session with *token_hash* to *seen_at*.

    The auth dependency throttles this to about once per five minutes per
    session, so it is not a write on every request.
    """
    with conn:
        conn.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
            (seen_at, token_hash),
        )


def delete(conn: sqlite3.Connection, token_hash: str) -> None:
    """Delete the session with *token_hash* (logout); a no-op when absent."""
    with conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_for_user(conn: sqlite3.Connection, user_id: int) -> None:
    """Delete every session owned by *user_id*, revoking their access."""
    with conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    log.info("appdb.sessions_revoked", user_id=user_id)


def prune_expired(conn: sqlite3.Connection, *, now_iso: str) -> int:
    """Delete every session whose ``expires_at`` is at or before *now_iso*.

    Called opportunistically (e.g. at login) to keep the table bounded.
    Returns the number of rows removed.
    """
    with conn:
        cursor = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_iso,))
    return cursor.rowcount
