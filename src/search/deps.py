"""FastAPI authentication and authorisation dependencies.

A ``search_session`` cookie is a logged-in human, bound by role only. An
``Authorization: Bearer sk-pls-...`` API key is bound by both its scopes and
its owner's role.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from fastapi import Depends, HTTPException, Request

from appdb import api_keys as key_store
from appdb import sessions as session_store
from appdb.connection import connect
from search.api_keys import (
    SCOPE_ADMIN,
    SCOPE_API,
    SCOPE_MCP,
    resolve_api_key,
    should_touch,
)
from search.appstate import AppState, get_app_state
from search.auth import SESSION_COOKIE_NAME, authorise_role, extract_bearer
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

    FastAPI caches a dependency within a request, so each request gets exactly
    one connection that no other request touches. That isolation is what makes
    ``sqlite3``'s non-thread-safe connections safe in FastAPI's threadpool.
    """
    conn = connect(state.app_db_path)
    try:
        yield conn
    finally:
        conn.close()


@dataclass(frozen=True, slots=True)
class Caller:
    """An authenticated request: identity plus, for an API key, its scopes.

    *scopes* is ``None`` for a cookie caller, meaning "not scope-limited"; an
    empty set would mean "no scopes". For an API key, *user* is the key's owner.
    """

    user: CurrentUser
    scopes: frozenset[str] | None
    api_key_id: int | None


def resolve_caller(
    request: Request,
    app_db: sqlite3.Connection = Depends(get_app_db),
) -> Caller:
    """Resolve the request to a :class:`Caller`, or raise ``401``.

    The session cookie is tried first, then the bearer API key. Usage
    timestamps are refreshed only when stale, so auth is not a write on every
    request.
    """
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    user = resolve_session(app_db, cookie_token)
    if user is not None:
        refresh_last_seen(app_db, cookie_token)
        return Caller(user=user, scopes=None, api_key_id=None)

    bearer = extract_bearer(request.headers.get("authorization"))
    resolved = resolve_api_key(app_db, bearer)
    if resolved is not None:
        _touch_api_key(app_db, resolved.api_key_id, resolved.last_used_at)
        return Caller(
            user=CurrentUser(
                id=resolved.owner_user_id,
                username=resolved.owner_username,
                role=resolved.owner_role,
                display_name=resolved.owner_display_name,
            ),
            scopes=resolved.scopes,
            api_key_id=resolved.api_key_id,
        )

    log.warning(
        "search.auth_rejected",
        has_cookie=cookie_token is not None,
        has_bearer=bearer is not None,
    )
    raise HTTPException(status_code=401, detail="Not authenticated")


def get_current_user(
    caller: Caller = Depends(resolve_caller),
) -> CurrentUser:
    """Resolve the request to a :class:`CurrentUser`, for routes that need no scope."""
    return caller.user


def _enforce(caller: Caller, *, required_role: str, required_scope: str) -> None:
    """Raise 403 unless *caller* satisfies the role and (for a key) the scope."""
    if not authorise_role(caller.user.role, required_role):
        log.warning(
            "search.rbac_denied",
            username=caller.user.username,
            user_role=caller.user.role,
            required_role=required_role,
        )
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to perform this action",
        )
    if caller.scopes is not None and required_scope not in caller.scopes:
        log.warning(
            "search.scope_denied",
            username=caller.user.username,
            required_scope=required_scope,
        )
        raise HTTPException(
            status_code=403,
            detail=f"This API key lacks the required '{required_scope}' scope",
        )


def require_role(required_role: str) -> Callable[..., CurrentUser]:
    """Return a dependency that requires at least *required_role*.

    It enforces no scope; use the scope dependencies for scope-gated routes.
    """

    def _dependency(
        caller: Caller = Depends(resolve_caller),
    ) -> CurrentUser:
        """Raise 403 unless the caller's role meets the requirement."""
        if not authorise_role(caller.user.role, required_role):
            log.warning(
                "search.rbac_denied",
                username=caller.user.username,
                user_role=caller.user.role,
                required_role=required_role,
            )
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action",
            )
        return caller.user

    return _dependency


def require_admin(
    caller: Caller = Depends(resolve_caller),
) -> CurrentUser:
    """Require an admin role and, for an API key, the ``admin`` scope."""
    _enforce(caller, required_role="admin", required_scope=SCOPE_ADMIN)
    return caller.user


def require_api_scope(
    caller: Caller = Depends(resolve_caller),
) -> CurrentUser:
    """Require read access to the ``/api/*`` data routes (``api`` scope for a key)."""
    _enforce(caller, required_role="readonly", required_scope=SCOPE_API)
    return caller.user


def require_api_scope_member(
    caller: Caller = Depends(resolve_caller),
) -> CurrentUser:
    """Require a Member-or-above role and, for a key, the ``api`` scope.

    Gates write actions such as the reconcile trigger.
    """
    _enforce(caller, required_role="member", required_scope=SCOPE_API)
    return caller.user


def require_mcp_scope(
    caller: Caller = Depends(resolve_caller),
) -> CurrentUser:
    """Require ``mcp`` access (the ``mcp`` scope for a key).

    The MCP ASGI middleware does its own check; this is for FastAPI-routed
    endpoints.
    """
    _enforce(caller, required_role="readonly", required_scope=SCOPE_MCP)
    return caller.user


def require_key_management(
    caller: Caller = Depends(resolve_caller),
) -> CurrentUser:
    """Gate the API-key management endpoints.

    Requires a Member-or-above role. An API key also needs the ``admin`` scope:
    managing credentials through a lesser key would be a privilege escalation.
    The ownership check is left to the handler, which has the key row.
    """
    _enforce(caller, required_role="member", required_scope=SCOPE_ADMIN)
    return caller.user


def refresh_last_seen(app_db: sqlite3.Connection, cookie_token: str | None) -> None:
    """Refresh the session's ``last_seen_at`` when it is stale.

    Public so the MCP ASGI middleware can use it too.
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


def _touch_api_key(
    app_db: sqlite3.Connection, api_key_id: int, last_used_at: str | None
) -> None:
    """Record a use of the API key when its usage stats are stale."""
    if should_touch(last_used_at):
        key_store.touch(
            app_db,
            api_key_id,
            used_at=datetime.now(timezone.utc).isoformat(),
        )
