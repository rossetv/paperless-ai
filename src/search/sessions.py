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
from dataclasses import dataclass

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
        id: The user's id, or ``0`` for the legacy ``SEARCH_API_KEY`` caller
            which has no user row.
        username: The user's login name, or a fixed sentinel for the legacy
            API-key caller.
        role: The role driving RBAC; always ``admin`` for the legacy caller.
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
