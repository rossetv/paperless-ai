"""First-run setup for the search server (web-redesign §4.5).

When ``app.db`` has no users, the server is in *setup mode*: it generates a
one-off setup token, logs it prominently to the container logs, and only
``/api/setup`` (guarded by that token) and the public status endpoint are
useful until the first admin is created.

The token is :func:`secrets.token_urlsafe`-generated, held only in memory
(:class:`SetupState`), and compared with :func:`hmac.compare_digest` so the
check is constant-time and leaks no prefix length. Restarting the server
before setup completes generates a fresh token and invalidates the old one —
multi-instance deployment is out of scope (spec §4.5).

``SetupState.token`` is set to ``None`` once setup is complete; from then on
:func:`verify_setup_token` rejects every candidate.

Allowed deps: stdlib (secrets, hmac), appdb.users. Forbidden: FastAPI,
sqlite3 SQL, store, daemon packages.
"""

from __future__ import annotations

import hmac
import secrets
import sqlite3
from dataclasses import dataclass

from appdb import users as user_store

# Setup-token entropy in bytes. 24 bytes is ample for a single-use,
# short-lived, log-delivered token.
_SETUP_TOKEN_BYTES = 24


@dataclass(slots=True)
class SetupState:
    """The in-memory holder for the current setup token.

    Mutable by design: the app factory creates one instance, stores the
    generated token on it, and the ``/api/setup`` handler clears it (sets it
    to ``None``) the moment the first admin is created. ``None`` means setup
    is complete and no token will verify.

    Attributes:
        token: The active setup token, or ``None`` when setup is complete.
    """

    token: str | None = None


def generate_setup_token() -> str:
    """Return a fresh, high-entropy, URL-safe setup token.

    Returns:
        A URL-safe token string suitable for logging and one-time use.
    """
    return secrets.token_urlsafe(_SETUP_TOKEN_BYTES)


def verify_setup_token(state: SetupState, candidate: str) -> bool:
    """Return whether *candidate* matches the held setup token.

    Fails closed: when ``state.token`` is ``None`` (setup already complete)
    every candidate is rejected. The comparison uses
    :func:`hmac.compare_digest` on the UTF-8 bytes so it is constant-time and
    does not leak the length of any matching prefix.

    Args:
        state: The setup-token holder.
        candidate: The token supplied in the setup request.

    Returns:
        ``True`` only when setup is active and *candidate* equals the token.
    """
    if state.token is None:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), state.token.encode("utf-8"))


def is_setup_needed(conn: sqlite3.Connection) -> bool:
    """Return whether first-run setup is still required.

    Setup is needed exactly when the ``users`` table is empty.

    Args:
        conn: An open ``app.db`` connection.

    Returns:
        ``True`` when no users exist.
    """
    return user_store.count_all(conn) == 0
