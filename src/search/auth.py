"""Authentication primitives for the search server (web-redesign §4).

Wave 1 replaced the shared-secret login with database-backed user accounts
and server-side sessions. The session lifecycle lives in
:mod:`search.sessions`; this module holds the pieces that are *not* the
session store:

- :func:`extract_bearer` — the one parser for the ``Authorization`` header,
  reused by the API dependency and the MCP middleware.
- :func:`verify_api_key` — a constant-time compare for the **legacy**
  ``SEARCH_API_KEY`` bearer token, which stays valid through Waves 1-2 as an
  admin-equivalent caller and is retired in Wave 3.
- :data:`LEGACY_API_KEY_USER` — the :class:`~search.sessions.CurrentUser`
  that a valid legacy key resolves to: a synthetic admin with no user row.
- :func:`authorise_role` — the pure RBAC predicate the role dependency uses.

This module is deliberately free of FastAPI so that
:mod:`search.mcp_server`, which imports it, keeps its narrow dependency set.
The FastAPI dependencies (``get_current_user``, ``require_role``) live in
:mod:`search.deps`.

Security invariants:

- Every secret comparison uses :func:`hmac.compare_digest` — constant-time.
- A failed credential check returns a value (``None`` / ``False``); it never
  raises, so a hostile request cannot trigger a 500.
- No secret — the API key, a session token — is ever logged.
"""

from __future__ import annotations

import hmac

from search.sessions import CurrentUser

# The session-cookie name. Unchanged from Wave 0 so existing browser sessions
# and the frontend's expectations are not disturbed.
SESSION_COOKIE_NAME = "search_session"

# The exact, case-sensitive prefix of an ``Authorization: Bearer`` header.
# The trailing space is part of the prefix.
_BEARER_PREFIX = "Bearer "

# The synthetic identity a valid legacy SEARCH_API_KEY bearer resolves to.
# id 0 marks "no user row"; role admin grants it every capability, matching
# the Wave 0 behaviour where the key was all-powerful. Retired in Wave 3.
LEGACY_API_KEY_USER = CurrentUser(id=0, username="legacy-api-key", role="admin")

# Role ranking for RBAC (web-redesign §4.3). A request satisfies a required
# role when the caller's rank is >= the requirement's rank.
_ROLE_RANK: dict[str, int] = {
    "readonly": 0,
    "member": 1,
    "admin": 2,
}


class AuthError(Exception):
    """Raised for a configuration-shaped authentication failure.

    A *failed credential check* is not an error — the verify helpers return
    ``False`` / ``None``. This type is for misconfiguration, e.g. asking to
    treat an empty ``SEARCH_API_KEY`` as a usable credential.
    """


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


def verify_api_key(provided: str, configured: str) -> bool:
    """Return whether *provided* equals *configured*, in constant time.

    Uses :func:`hmac.compare_digest` on the UTF-8 bytes so the comparison
    takes the same time regardless of where the values first differ — an
    ``==`` comparison leaks the matching-prefix length through timing.
    Comparing bytes also avoids a ``TypeError`` on non-ASCII input.

    An empty *configured* key always returns ``False``: a deployment with no
    legacy key set must not be unlocked by an empty bearer token.

    Args:
        provided: The bearer token from the request.
        configured: The configured ``SEARCH_API_KEY``.

    Returns:
        ``True`` only when both are non-empty and equal.
    """
    if not configured:
        return False
    return hmac.compare_digest(
        provided.encode("utf-8"), configured.encode("utf-8")
    )


def legacy_api_key_user(
    bearer: str | None, configured_key: str
) -> CurrentUser | None:
    """Return :data:`LEGACY_API_KEY_USER` for a valid legacy bearer, else None.

    The legacy ``SEARCH_API_KEY`` path: a request whose bearer token equals
    the configured key is treated as a synthetic admin caller (Waves 1-2).

    Args:
        bearer: The extracted bearer token, or ``None``.
        configured_key: The configured ``SEARCH_API_KEY`` (may be empty).

    Returns:
        The synthetic admin :class:`CurrentUser` on a match, else ``None``.
    """
    if bearer is None:
        return None
    if verify_api_key(bearer, configured_key):
        return LEGACY_API_KEY_USER
    return None


def authorise_role(user_role: str, required_role: str) -> bool:
    """Return whether *user_role* satisfies *required_role* (web-redesign §4.3).

    Roles are ranked ``readonly`` < ``member`` < ``admin``; a caller is
    authorised when its rank is at least the requirement's. An unknown role
    string ranks below everything, so it is never authorised — fail closed.

    Args:
        user_role: The authenticated caller's role.
        required_role: The role the route demands.

    Returns:
        ``True`` when the caller's role is sufficient.
    """
    caller_rank = _ROLE_RANK.get(user_role, -1)
    required_rank = _ROLE_RANK.get(required_role, -1)
    if required_rank < 0:
        # An unknown requirement is a programming error — fail closed.
        return False
    return caller_rank >= required_rank
