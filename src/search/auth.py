"""Auth helpers shared by the FastAPI dependencies and the MCP middleware.

Kept free of FastAPI so :mod:`search.mcp_server` stays light. A failed
credential check returns ``None`` / ``False`` rather than raising, so a hostile
request cannot cause a 500, and no secret is ever logged.
"""

from __future__ import annotations

import sqlite3

from search.api_keys import resolve_api_key
from search.sessions import CurrentUser

# Changing this would sign out every existing browser session.
SESSION_COOKIE_NAME = "search_session"

_BEARER_PREFIX = "Bearer "

# A caller satisfies a required role when its rank is >= the requirement's.
_ROLE_RANK: dict[str, int] = {
    "readonly": 0,
    "member": 1,
    "admin": 2,
}


def extract_bearer(authorization_header: str | None) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` header.

    Shared by the REST and MCP surfaces so both accept the same header shape.
    The ``"Bearer "`` prefix is case-sensitive.
    """
    if authorization_header is None or not authorization_header.startswith(
        _BEARER_PREFIX
    ):
        return None
    return authorization_header[len(_BEARER_PREFIX) :]


def api_key_caller(conn: sqlite3.Connection, bearer: str | None) -> CurrentUser | None:
    """Resolve a bearer API key to its owner as a :class:`CurrentUser`, or ``None``.

    The key's scopes are not carried; :mod:`search.deps` enforces them.
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
    """Return whether *user_role* satisfies *required_role*.

    An unknown role or an unknown requirement fails closed.
    """
    caller_rank = _ROLE_RANK.get(user_role, -1)
    required_rank = _ROLE_RANK.get(required_role, -1)
    if required_rank < 0:
        return False
    return caller_rank >= required_rank
