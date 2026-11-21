"""First-run setup: the one-off token that guards creating the first admin.

While ``app.db`` has no users the server logs a setup token and accepts it on
``/api/setup``. The token lives only in memory, so a restart before setup
completes replaces it; a multi-instance deployment is not supported.
"""

from __future__ import annotations

import hmac
import secrets
import sqlite3
from dataclasses import dataclass

from appdb import users as user_store

# 24 bytes is ample for a single-use, short-lived token.
_SETUP_TOKEN_BYTES = 24


@dataclass(slots=True)
class SetupState:
    """The in-memory setup token; ``None`` once the first admin exists."""

    token: str | None = None


def generate_setup_token() -> str:
    """Return a fresh, URL-safe setup token."""
    return secrets.token_urlsafe(_SETUP_TOKEN_BYTES)


def verify_setup_token(state: SetupState, candidate: str) -> bool:
    """Return whether *candidate* matches the held token, in constant time.

    Rejects everything once setup is complete.
    """
    if state.token is None:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), state.token.encode("utf-8"))


def is_setup_needed(conn: sqlite3.Connection) -> bool:
    """Return whether first-run setup is still required (no users exist)."""
    return user_store.count_all(conn) == 0
