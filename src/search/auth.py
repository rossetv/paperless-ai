"""Authentication primitives for the search server (web-redesign §4, §5).

The session lifecycle lives in :mod:`search.sessions`; the API-key lifecycle
in :mod:`search.api_keys`. This module holds the pieces shared by the FastAPI
dependencies and the MCP middleware that are *neither* store:

- :func:`extract_bearer` — the one parser for the ``Authorization`` header.
- :func:`api_key_caller` — turn a presented raw API key into a
  :class:`~search.sessions.CurrentUser`, via the database-backed
  :func:`search.api_keys.resolve_api_key`.
- :func:`authorise_role` — the pure RBAC predicate the role dependency uses.

Wave 3 retired the legacy shared secret: ``SEARCH_API_KEY`` no longer grants
access. A fresh install has zero programmatic access until an API key is
minted in the UI — there is no default credential (web-redesign §2). The
Wave 1 ``verify_api_key`` / ``legacy_api_key_user`` / ``LEGACY_API_KEY_USER``
are gone with it.

This module is deliberately free of FastAPI so :mod:`search.mcp_server`,
which imports it, keeps its narrow dependency set. The FastAPI dependencies
(``get_current_user``, ``require_role``, the scope dependencies) live in
:mod:`search.deps`.

Security invariants:

- A failed credential check returns a value (``None`` / ``False``); it never
  raises, so a hostile request cannot trigger a 500.
- No secret — an API key, a session token — is ever logged.
"""

from __future__ import annotations

import sqlite3

from search.api_keys import resolve_api_key
from search.sessions import CurrentUser

# The session-cookie name. Unchanged since Wave 1 so existing browser
# sessions and the frontend's expectations are not disturbed.
SESSION_COOKIE_NAME = "search_session"

# The exact, case-sensitive prefix of an ``Authorization: Bearer`` header.
# The trailing space is part of the prefix.
_BEARER_PREFIX = "Bearer "

# Role ranking for RBAC (web-redesign §4.3). A request satisfies a required
# role when the caller's rank is >= the requirement's rank.
_ROLE_RANK: dict[str, int] = {
    "readonly": 0,
    "member": 1,
    "admin": 2,
}


def extract_bearer(authorization_header: str | None) -> str | None:
    """Extract the raw token from an ``Authorization: Bearer <token>`` header.

    The single shared parser, reused by the FastAPI auth dependency and the
    MCP bearer-auth middleware so both surfaces accept exactly the same
    header shape.

    Args:
        authorization_header: The raw ``Authorization`` header value, or
            ``None`` when the request carried no such header.

    Returns:
        The token string when the header starts with the case-sensitive
        prefix ``"Bearer "``; ``None`` otherwise. The token is never logged.
    """
    if authorization_header is None or not authorization_header.startswith(
        _BEARER_PREFIX
    ):
        return None
    return authorization_header[len(_BEARER_PREFIX) :]


def api_key_caller(conn: sqlite3.Connection, bearer: str | None) -> CurrentUser | None:
    """Resolve an ``Authorization: Bearer`` API key to a :class:`CurrentUser`.

    Delegates to :func:`search.api_keys.resolve_api_key`, which hashes the
    presented key, looks it up, and rejects a missing / revoked / expired
    key or a suspended owner. On success the returned identity carries the
    **owner's** id, username and role — a key never grants more than its
    owner's role allows.

    The key's *scopes* are not on :class:`CurrentUser`; scope enforcement is
    a separate concern handled by the dependencies in :mod:`search.deps`,
    which call :func:`search.api_keys.resolve_api_key` directly.

    Args:
        conn: The open ``app.db`` connection.
        bearer: The extracted bearer token, or ``None``.

    Returns:
        A :class:`CurrentUser` for the key's owner on success, else ``None``.
    """
    resolved = resolve_api_key(conn, bearer)
    if resolved is None:
        return None
    return CurrentUser(
        id=resolved.owner_user_id,
        username=resolved.owner_username,
        role=resolved.owner_role,
    )


def authorise_role(user_role: str, required_role: str) -> bool:
    """Return whether *user_role* satisfies *required_role* (web-redesign §4.3).

    Roles are ranked ``readonly`` < ``member`` < ``admin``; a caller is
    authorised when its rank is at least the requirement's. An unknown role
    string ranks below everything, so it is never authorised — fail closed.
    An unknown *requirement* is a programming error and also fails closed.

    Args:
        user_role: The authenticated caller's role.
        required_role: The role the route demands.

    Returns:
        ``True`` when the caller's role is sufficient.
    """
    caller_rank = _ROLE_RANK.get(user_role, -1)
    required_rank = _ROLE_RANK.get(required_role, -1)
    if required_rank < 0:
        return False
    return caller_rank >= required_rank
