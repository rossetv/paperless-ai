"""Server-side browser sessions.

The cookie holds an opaque random token; only its SHA-256 is stored, so a
database leak yields no usable sessions. With a server-side store there is
nothing to sign, and revocation is a row delete. The cookie is
``SameSite=Strict``, which is the CSRF defence, so there is no CSRF token.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import overload

from appdb import sessions as session_store
from appdb import users as user_store

_TOKEN_BYTES = 32

# A login without "keep me signed in"; with it, SEARCH_SESSION_TTL applies.
SESSION_TTL_SECONDS = 28800  # 8 hours


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The authenticated identity handed to a route handler.

    *display_name* is the search's "who is asking" signal.
    """

    id: int
    username: str
    role: str
    display_name: str | None = None


def new_token() -> str:
    """Return a fresh 256-bit URL-safe session token."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest stored in ``sessions.token_hash``.

    The token is full-entropy random, so a fast hash suffices; no slow KDF.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cookie_ttl_seconds(*, remember: bool, remember_ttl_seconds: int) -> int:
    """Return the cookie/session lifetime in seconds for a login."""
    return remember_ttl_seconds if remember else SESSION_TTL_SECONDS


# How stale last_seen_at may get before a request refreshes it.
_LAST_SEEN_REFRESH = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A new session: the raw cookie token (never stored) and its expiry."""

    token: str
    expires_at: str


def begin_session(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    ttl_seconds: int,
    user_agent: str | None = None,
    ip: str | None = None,
) -> IssuedSession:
    """Create a session for *user_id* and return its raw token and expiry."""
    token = new_token()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    ).isoformat()
    session_store.create(
        conn,
        token_hash=hash_token(token),
        user_id=user_id,
        expires_at=expires_at,
        user_agent=user_agent,
        ip=ip,
    )
    # Sweep expired sessions whose cookie is never presented again (resolve
    # prunes the rest). Login is a cold path and expires_at is indexed.
    session_store.prune_expired(conn, now_iso=datetime.now(timezone.utc).isoformat())
    return IssuedSession(token=token, expires_at=expires_at)


def resolve_session(conn: sqlite3.Connection, token: str | None) -> CurrentUser | None:
    """Resolve a cookie token to a :class:`CurrentUser`, or ``None``.

    Fails closed on an unknown or expired session or a missing or suspended
    user. An expired session row is deleted on the way.
    """
    if token is None:
        return None

    token_hash = hash_token(token)
    session = session_store.get_by_token_hash(conn, token_hash)
    if session is None:
        return None

    now = datetime.now(timezone.utc)
    if _parse_iso(session.expires_at, default=now) <= now:
        session_store.delete(conn, token_hash)
        return None

    user = user_store.get_by_id(conn, session.user_id)
    if user is None or user.status != "active":
        return None

    return CurrentUser(
        id=user.id,
        username=user.username,
        role=user.role,
        display_name=user.display_name,
    )


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    """Destroy the session identified by the cookie *token*, if any."""
    if token is None:
        return
    session_store.delete(conn, hash_token(token))


def should_touch_last_seen(last_seen_at: str) -> bool:
    """Return whether ``last_seen_at`` is stale enough to warrant a write.

    An unparseable timestamp counts as stale, so the next write repairs it.
    """
    now = datetime.now(timezone.utc)
    parsed = _parse_iso(last_seen_at, default=None)
    if parsed is None:
        return True
    return (now - parsed) > _LAST_SEEN_REFRESH


@overload
def _parse_iso(value: str, *, default: datetime) -> datetime: ...


@overload
def _parse_iso(value: str, *, default: None) -> datetime | None: ...


def _parse_iso(value: str, *, default: datetime | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning *default* on a malformed value.

    The overloads tell the type checker a non-``None`` *default* gives a
    non-``None`` result.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return default
    # A tz-naive value (e.g. a hand-edited row) is read as UTC, so comparing it
    # with an aware "now" cannot raise.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
