"""Server-side session management for the search server (web-redesign §4.4).

This module owns the session lifecycle the browser auth flow needs, on top
of the :mod:`appdb.sessions` table:

- :func:`new_token` mints a high-entropy opaque token for the cookie.
- :func:`hash_token` is the SHA-256 the database stores — the raw token is
  never persisted, so a database leak yields no usable sessions.
- :class:`CurrentUser` is the small, role-carrying identity the FastAPI
  dependencies hand to route handlers.
- :func:`begin_session` / :func:`resolve_session` / :func:`end_session`
  create, look up, and destroy sessions against ``app.db`` (added in the
  next task).

The token is opaque (no signature, no embedded claims): with a server-side
store there is nothing to sign, and revocation is a row delete. The cookie
is ``SameSite=Strict``, so cross-site requests never carry it — that is the
CSRF defence; no separate CSRF token is added (spec §4.4).

Allowed deps: stdlib (secrets, hashlib), appdb (sessions, users). Forbidden:
FastAPI, sqlite3 directly, store, daemon packages.
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

# Token entropy in bytes. 32 bytes (256 bits) is well beyond brute-force.
_TOKEN_BYTES = 32

# Session lifetimes in seconds (spec §4.4). The "keep me signed in" tick
# selects REMEMBER_TTL_SECONDS; an un-ticked login gets the shorter one.
SESSION_TTL_SECONDS = 28800  # 8 hours
REMEMBER_TTL_SECONDS = 604800  # 7 days


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The authenticated identity handed to a route handler.

    A deliberately small projection of the full :class:`appdb.users.User`:
    the route layer needs the id (for self-action guards), the username (for
    logging and display), and the role (for RBAC) — and nothing else.

    Attributes:
        id: The user's ``users`` row id.
        username: The user's login name.
        role: The role driving RBAC.
    """

    id: int
    username: str
    role: str


def new_token() -> str:
    """Return a fresh, high-entropy, URL-safe opaque session token.

    The value placed in the ``search_session`` cookie. It is never stored as
    given — :func:`hash_token` produces what the database holds.

    Returns:
        A URL-safe token string of at least 256 bits of entropy.
    """
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of *token*.

    This is the value stored in ``sessions.token_hash``. SHA-256 (a fast
    hash, not a password hash) is correct here: a session token is already
    full-entropy random, so it needs no slow KDF — only a one-way mapping so
    the raw token is absent from the database.

    Args:
        token: The opaque session token from the cookie.

    Returns:
        The 64-character lowercase hex SHA-256 digest.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cookie_ttl_seconds(*, remember: bool) -> int:
    """Return the cookie/session lifetime in seconds for a login.

    Args:
        remember: ``True`` when the user ticked "keep me signed in".

    Returns:
        :data:`REMEMBER_TTL_SECONDS` when *remember* is set, otherwise
        :data:`SESSION_TTL_SECONDS`.
    """
    return REMEMBER_TTL_SECONDS if remember else SESSION_TTL_SECONDS


# How stale last_seen_at may get before a request triggers a refresh write.
# ~5 minutes (spec §4.4) keeps last_seen useful without a write per request.
_LAST_SEEN_REFRESH = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """The result of :func:`begin_session`.

    Attributes:
        token: The raw opaque token to place in the ``search_session``
            cookie. It is *not* stored anywhere — only its hash is.
        expires_at: The ISO-8601 UTC expiry of the new session.
    """

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
    """Create a session for *user_id* and return its raw token and expiry.

    Mints a fresh opaque token, inserts a ``sessions`` row keyed by the
    token's SHA-256 hash, and returns the raw token for the caller to set as
    the cookie. The raw token is never persisted.

    Args:
        conn: An open ``app.db`` connection.
        user_id: The id of the user the session belongs to.
        ttl_seconds: The session lifetime in seconds (from
            :func:`cookie_ttl_seconds`).
        user_agent: The login request's ``User-Agent``, or ``None``.
        ip: The login request's client IP, or ``None``.

    Returns:
        An :class:`IssuedSession` with the raw token and the expiry.
    """
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
    return IssuedSession(token=token, expires_at=expires_at)


def resolve_session(conn: sqlite3.Connection, token: str | None) -> CurrentUser | None:
    """Resolve a cookie token to a :class:`CurrentUser`, or ``None``.

    Hashes *token*, looks up the session, and returns ``None`` — failing
    closed — when any of the following holds: *token* is absent; no session
    matches; the session has expired; the owning user no longer exists; the
    owning user is suspended. An expired session row is deleted as a side
    effect, so a dead session is also cleaned up.

    Args:
        conn: An open ``app.db`` connection.
        token: The raw session token from the cookie, or ``None``.

    Returns:
        The :class:`CurrentUser` for a live, active session; otherwise
        ``None``.
    """
    if token is None:
        return None

    token_hash = hash_token(token)
    session = session_store.get_by_token_hash(conn, token_hash)
    if session is None:
        return None

    # Reject (and prune) an expired session.
    now = datetime.now(timezone.utc)
    if _parse_iso(session.expires_at, default=now) <= now:
        session_store.delete(conn, token_hash)
        return None

    user = user_store.get_by_id(conn, session.user_id)
    if user is None or user.status != "active":
        # The user was deleted or suspended — fail closed.
        return None

    return CurrentUser(id=user.id, username=user.username, role=user.role)


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    """Destroy the session identified by the cookie *token* (logout).

    A no-op when *token* is ``None`` or matches no session.

    Args:
        conn: An open ``app.db`` connection.
        token: The raw session token from the cookie, or ``None``.
    """
    if token is None:
        return
    session_store.delete(conn, hash_token(token))


def should_touch_last_seen(last_seen_at: str) -> bool:
    """Return whether ``last_seen_at`` is stale enough to warrant a write.

    Throttles the per-request ``last_seen`` update: ``True`` only when the
    stored timestamp is older than the ~5-minute refresh window, so the
    common case is a read with no write. An unparseable timestamp is treated
    as stale so the next request repairs it.

    Args:
        last_seen_at: The session's stored ``last_seen_at`` ISO-8601 string.

    Returns:
        ``True`` when the timestamp should be refreshed.
    """
    now = datetime.now(timezone.utc)
    # _parse_iso is called with default=None, so an unparseable stored
    # timestamp yields None — treated as stale here so the next request
    # rewrites last_seen_at with a well-formed value and repairs the row.
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

    The overloads let the type checker see that a non-``None`` *default*
    yields a non-``None`` result — :func:`resolve_session` relies on that to
    compare the parsed expiry against the clock without a redundant guard.

    Args:
        value: The ISO-8601 string to parse.
        default: What to return when *value* cannot be parsed.

    Returns:
        The parsed timezone-aware :class:`~datetime.datetime`, or *default*.
    """
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return default
