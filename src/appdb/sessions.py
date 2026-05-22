"""Server-side sessions in the application database — the ``sessions`` table.

This module owns the :class:`Session` dataclass and the typed query functions
over the ``sessions`` table. Sessions are server-side (spec §2, "Sessions")
so that suspending or deleting a user revokes their access *instantly* — a
stateless token cannot be revoked.

The cookie carries an opaque random token; this table stores only
``sha256(token)`` (spec §4.2, §4.4). A database leak therefore does not yield
usable session tokens. Hashing the cookie token into ``token_hash`` is the
caller's job (the search server's auth layer); this module is told the hash.

Expiry is *not* enforced by :func:`get_by_token_hash` — it returns a row even
when ``expires_at`` is in the past, so the caller can both reject the request
and prune the dead row. :func:`prune_expired` is the bulk sweep.

Allowed deps: sqlite3, structlog. Forbidden: store, search, daemon packages,
FastAPI.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Session:
    """One row of the ``sessions`` table — a live server-side session.

    Attributes:
        id: The integer primary key.
        token_hash: The SHA-256 hex digest of the opaque cookie token. The
            raw token is never stored.
        user_id: The owning user's id; cascades on user deletion.
        created_at: ISO-8601 UTC creation timestamp.
        expires_at: ISO-8601 UTC expiry; the caller compares it to the clock.
        last_seen_at: ISO-8601 UTC timestamp of the last request that used
            this session.
        user_agent: The ``User-Agent`` of the creating request, or ``None``.
        ip: The client IP of the creating request, or ``None``.
    """

    id: int
    token_hash: str
    user_id: int
    created_at: str
    expires_at: str
    last_seen_at: str
    user_agent: str | None
    ip: str | None


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``+00:00``
    offset — the timestamp format the ``sessions`` table stores."""
    return datetime.now(timezone.utc).isoformat()


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


# The column list shared by every SELECT.
_SESSION_COLUMNS = (
    "id, token_hash, user_id, created_at, expires_at, last_seen_at, "
    "user_agent, ip"
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
    """Insert a new session and return it fully populated.

    ``created_at`` and ``last_seen_at`` are set to the current UTC time.

    Args:
        conn: An open, migrated ``app.db`` connection.
        token_hash: The SHA-256 hex digest of the cookie token.
        user_id: The owning user's id.
        expires_at: The ISO-8601 UTC expiry timestamp.
        user_agent: The creating request's ``User-Agent``, or ``None``.
        ip: The creating request's client IP, or ``None``.

    Returns:
        The created :class:`Session`.
    """
    now = _utc_now_iso()
    cursor = conn.execute(
        "INSERT INTO sessions "
        "(token_hash, user_id, created_at, expires_at, last_seen_at, "
        " user_agent, ip) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (token_hash, user_id, now, expires_at, now, user_agent, ip),
    )
    conn.commit()
    log.info("appdb.session_created", session_id=cursor.lastrowid, user_id=user_id)
    row = conn.execute(
        f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    # The row was just inserted in this connection — it must be present.
    assert row is not None
    return _row_to_session(row)


def get_by_token_hash(
    conn: sqlite3.Connection, token_hash: str
) -> Session | None:
    """Return the session whose ``token_hash`` matches, or ``None``.

    The row is returned even when ``expires_at`` is in the past — expiry is
    the caller's check (so it can reject the request and prune the row).

    Args:
        conn: An open ``app.db`` connection.
        token_hash: The SHA-256 hex digest to look up.
    """
    row = conn.execute(
        f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE token_hash = ?",
        (token_hash,),
    ).fetchone()
    return _row_to_session(row) if row is not None else None


def touch_last_seen(
    conn: sqlite3.Connection, token_hash: str, *, seen_at: str
) -> None:
    """Set ``last_seen_at`` for the session with *token_hash* to *seen_at*.

    The caller (the auth dependency) throttles this to roughly once every
    five minutes per session, so it is not a write on every request.

    Args:
        conn: An open ``app.db`` connection.
        token_hash: The session's token hash.
        seen_at: The ISO-8601 UTC timestamp to record.
    """
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
        (seen_at, token_hash),
    )
    conn.commit()


def delete(conn: sqlite3.Connection, token_hash: str) -> None:
    """Delete the session with *token_hash*; a no-op when it does not exist.

    This is the logout path.

    Args:
        conn: An open ``app.db`` connection.
        token_hash: The session's token hash.
    """
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
    conn.commit()


def delete_for_user(conn: sqlite3.Connection, user_id: int) -> None:
    """Delete every session owned by *user_id*.

    This is how suspending or deleting a user revokes access instantly —
    every session row of that user is removed.

    Args:
        conn: An open ``app.db`` connection.
        user_id: The owning user's id.
    """
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    log.info("appdb.sessions_revoked", user_id=user_id)


def prune_expired(conn: sqlite3.Connection, *, now_iso: str) -> int:
    """Delete every session whose ``expires_at`` is at or before *now_iso*.

    Called opportunistically (e.g. at login) to keep the table from growing
    without bound. Returns the number of rows removed.

    Args:
        conn: An open ``app.db`` connection.
        now_iso: The ISO-8601 UTC cutoff; rows with ``expires_at <= now_iso``
            are removed.

    Returns:
        The count of pruned rows.
    """
    cursor = conn.execute(
        "DELETE FROM sessions WHERE expires_at <= ?", (now_iso,)
    )
    conn.commit()
    return cursor.rowcount
