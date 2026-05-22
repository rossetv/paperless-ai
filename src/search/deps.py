"""FastAPI authentication and authorisation dependencies (web-redesign §4.3).

This module holds the request-time auth dependencies, kept separate from
:mod:`search.auth` so that module stays free of FastAPI (it is imported by
:mod:`search.mcp_server`).

- :func:`get_app_db` opens one ``app.db`` connection per request and closes it
  when the request ends. FastAPI caches a dependency's result within a single
  request, so the connection is created exactly once per request and shared,
  *sequentially*, by that request's dependency chain and route handler — never
  by two requests at once. A ``sqlite3.Connection`` driven concurrently from
  the request threadpool corrupts data; one connection per request is the fix.
- :func:`get_current_user` resolves a request to a
  :class:`~search.sessions.CurrentUser`, accepting **either** a
  ``search_session`` cookie (a real user) **or** an ``Authorization: Bearer
  <SEARCH_API_KEY>`` legacy token (a synthetic admin, Waves 1-2). It raises
  ``401`` when neither credential is valid.
- :func:`require_role` is a dependency *factory*: ``require_role("member")``
  returns a dependency that resolves the user and raises ``403`` when the
  role is insufficient.
- :data:`require_admin` is the common ``require_role("admin")``.
- :func:`refresh_last_seen` is the shared ``last_seen_at`` touch-throttle, used
  by both the HTTP auth path and the MCP cookie-auth path.

``last_seen_at`` on a resolved session is refreshed at most once every ~5
minutes (the throttle in :mod:`search.sessions`), so authentication is not a
database write on every request.

Allowed deps: fastapi, structlog, appdb, search (auth, sessions, appstate).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime, timezone

import structlog
from fastapi import Depends, HTTPException, Request

from appdb import sessions as session_store
from appdb.connection import connect
from search.appstate import AppState, get_app_state
from search.auth import (
    SESSION_COOKIE_NAME,
    authorise_role,
    extract_bearer,
    legacy_api_key_user,
)
from search.sessions import (
    CurrentUser,
    hash_token,
    resolve_session,
    should_touch_last_seen,
)

log = structlog.get_logger(__name__)


def get_app_db(
    state: AppState = Depends(get_app_state),
) -> Iterator[sqlite3.Connection]:
    """Yield a fresh ``app.db`` connection for the current request, then close it.

    A FastAPI ``yield`` dependency: the connection is opened from
    ``state.app_db_path``, handed to the request's dependency chain and route
    handler, and closed in the ``finally`` when the request ends. FastAPI
    caches a dependency within one request, so this opens exactly one
    connection per request — used strictly sequentially by that request, never
    shared with another. That per-request isolation is what makes
    ``sqlite3``'s non-thread-safe connections correct under FastAPI's
    threadpool execution model.

    Args:
        state: The application's account context (injected).

    Yields:
        An open ``app.db`` connection scoped to this request.
    """
    conn = connect(state.app_db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(
    request: Request,
    app_db: sqlite3.Connection = Depends(get_app_db),
    state: AppState = Depends(get_app_state),
) -> CurrentUser:
    """Resolve the request to a :class:`CurrentUser`, or raise ``401``.

    Tries, in order: the ``search_session`` cookie (a database session for a
    real user) and the ``Authorization: Bearer`` header (the legacy
    ``SEARCH_API_KEY``, a synthetic admin). The first that resolves wins. If
    a cookie session resolves, its ``last_seen_at`` is refreshed when stale.

    Args:
        request: The incoming request.
        app_db: The per-request ``app.db`` connection (injected).
        state: The application's account context (injected).

    Returns:
        The authenticated :class:`CurrentUser`.

    Raises:
        HTTPException: ``401`` when no valid credential is present.
    """
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    user = resolve_session(app_db, cookie_token)
    if user is not None:
        refresh_last_seen(app_db, cookie_token)
        return user

    bearer = extract_bearer(request.headers.get("authorization"))
    legacy_user = legacy_api_key_user(bearer, state.legacy_api_key)
    if legacy_user is not None:
        return legacy_user

    log.warning(
        "search.auth_rejected",
        has_cookie=cookie_token is not None,
        has_bearer=bearer is not None,
    )
    raise HTTPException(status_code=401, detail="Not authenticated")


def require_role(required_role: str) -> Callable[..., CurrentUser]:
    """Return a FastAPI dependency that requires at least *required_role*.

    The dependency resolves the current user via :func:`get_current_user`
    (so an unauthenticated request still gets ``401``) and then checks the
    role, raising ``403`` when it is insufficient. Roles rank
    ``readonly`` < ``member`` < ``admin``.

    Args:
        required_role: The minimum role the route demands.

    Returns:
        A FastAPI dependency callable resolving to the authorised
        :class:`~search.sessions.CurrentUser`.
    """

    def _dependency(
        user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        """Raise 403 unless *user*'s role meets the requirement."""
        if not authorise_role(user.role, required_role):
            log.warning(
                "search.rbac_denied",
                username=user.username,
                user_role=user.role,
                required_role=required_role,
            )
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action",
            )
        return user

    return _dependency


# The common admin gate, pre-built so route declarations read cleanly.
require_admin = require_role("admin")


def refresh_last_seen(app_db: sqlite3.Connection, cookie_token: str | None) -> None:
    """Refresh the session's ``last_seen_at`` when it is stale.

    A no-op when *cookie_token* is absent or the stored timestamp is recent,
    so this is a database write only roughly once every five minutes per
    session. Shared by the HTTP auth dependency and the MCP cookie-auth
    middleware so a cookie-only MCP client's ``last_seen_at`` does not freeze.

    Args:
        app_db: An open ``app.db`` connection.
        cookie_token: The raw session token from the cookie.
    """
    if cookie_token is None:
        return
    token_hash = hash_token(cookie_token)
    session = session_store.get_by_token_hash(app_db, token_hash)
    if session is None:
        return
    if should_touch_last_seen(session.last_seen_at):
        session_store.touch_last_seen(
            app_db,
            token_hash,
            seen_at=datetime.now(timezone.utc).isoformat(),
        )
