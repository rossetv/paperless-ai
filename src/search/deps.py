"""FastAPI authentication and authorisation dependencies (web-redesign §4-5).

The request-time auth dependencies, kept separate from :mod:`search.auth` so
that module stays free of FastAPI (it is imported by
:mod:`search.mcp_server`).

Two credential kinds reach these dependencies:

- A ``search_session`` cookie — a logged-in human. Their role is the only
  bound on what they may do; cookie callers are **not** scope-limited.
- An ``Authorization: Bearer sk-pls-...`` API key — a programmatic caller.
  Bound by *both* the key's scopes (``api``/``mcp``/``admin``) *and* the
  owning user's role.

The legacy ``SEARCH_API_KEY`` bearer is gone (Wave 3): a fresh install has
zero programmatic access until a key is minted.

Surface:

- :func:`get_app_db` — opens one ``app.db`` connection per request and closes
  it when the request ends.
- :func:`resolve_caller` — request -> :class:`Caller` (identity + optional
  key scopes), or ``401``.
- :func:`get_current_user` — request -> :class:`~search.sessions.CurrentUser`,
  or ``401``. The Wave 1 signature, used by routes that need only identity.
- :func:`require_role` — a factory; the returned dependency ``403``s on an
  insufficient role.
- :func:`require_admin` — an admin role plus, for an API key, the ``admin``
  scope.
- :func:`require_api_scope` / :func:`require_api_scope_member` /
  :func:`require_mcp_scope` — gate a route on the ``api`` / ``mcp`` scope (a
  no-op extra check for a cookie caller).
- :func:`require_key_management` — gate the API-key management endpoints: a
  Member+ role, plus the ``admin`` scope for an API-key caller.

``last_seen_at`` on a resolved session is refreshed at most once every ~5
minutes; an API key's ``last_used_at`` at most once every ~60 s — so
authentication is not a database write on every request.

Allowed deps: fastapi, structlog, sqlite3, appdb, search (auth, api_keys,
sessions, appstate).
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


@dataclass(frozen=True, slots=True)
class Caller:
    """An authenticated request — identity plus, for an API key, its scopes.

    Attributes:
        user: The :class:`CurrentUser` (for an API key, the key's *owner*).
        scopes: The API key's scope set, or ``None`` when the caller is a
            logged-in human (a cookie session). ``None`` means
            "not scope-limited"; an empty set would mean "no scopes".
        api_key_id: The matched ``api_keys`` row id, or ``None`` for a cookie
            caller. Used only for usage tracking.
    """

    user: CurrentUser
    scopes: frozenset[str] | None
    api_key_id: int | None


def resolve_caller(
    request: Request,
    app_db: sqlite3.Connection = Depends(get_app_db),
) -> Caller:
    """Resolve the request to a :class:`Caller`, or raise ``401``.

    Tries the ``search_session`` cookie first (a human), then the
    ``Authorization: Bearer`` API key. The first that resolves wins. A
    resolved cookie session has its ``last_seen_at`` refreshed when stale; a
    resolved API key has its ``last_used_at``/``request_count`` touched when
    stale.

    Args:
        request: The incoming request.
        app_db: The per-request ``app.db`` connection (injected). The
            connection is opened by :func:`get_app_db` and scoped to this
            request — never shared across requests.

    Returns:
        The authenticated :class:`Caller`.

    Raises:
        HTTPException: ``401`` when no valid credential is present.
    """
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    user = resolve_session(app_db, cookie_token)
    if user is not None:
        _refresh_last_seen(app_db, cookie_token)
        # A cookie caller is a human — bounded by role only, not by scopes.
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
    """Resolve the request to a :class:`CurrentUser` (the Wave 1 signature).

    A thin projection of :func:`resolve_caller` for routes that need only the
    caller's identity and role, not scope information.

    Args:
        caller: The resolved caller (injected).

    Returns:
        The authenticated :class:`CurrentUser`.
    """
    return caller.user


def _enforce(caller: Caller, *, required_role: str, required_scope: str) -> None:
    """Raise 403 unless *caller* satisfies the role and (for a key) the scope.

    Two independent checks:

    - The role: ``caller.user.role`` must rank at or above *required_role*.
    - The scope: only when the caller is an API key (``caller.scopes`` is not
      ``None``) — the key must hold *required_scope*. A cookie caller (a
      human) is not scope-limited, so the scope check is skipped for them.

    Args:
        caller: The resolved caller.
        required_role: The minimum role the route demands.
        required_scope: The API-key scope the route demands.

    Raises:
        HTTPException: ``403`` on an insufficient role, or an API key that
            lacks the scope.
    """
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
    """Return a FastAPI dependency that requires at least *required_role*.

    The dependency resolves the caller (so an unauthenticated request still
    gets ``401``) and then checks the role, raising ``403`` when it is
    insufficient. It does **not** enforce a scope — use the scope
    dependencies for scope-gated routes. Roles rank
    ``readonly`` < ``member`` < ``admin``.

    Args:
        required_role: The minimum role the route demands.

    Returns:
        A FastAPI dependency callable yielding the :class:`CurrentUser`.
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
    """FastAPI dependency: require an admin role and the ``admin`` key scope.

    Gates user and API-key administration. A logged-in admin passes on role
    alone; an API key must additionally carry the ``admin`` scope.

    Args:
        caller: The resolved caller (injected).

    Returns:
        The admin :class:`CurrentUser`.

    Raises:
        HTTPException: ``403`` for a non-admin, or an API key without the
            ``admin`` scope.
    """
    _enforce(caller, required_role="admin", required_scope=SCOPE_ADMIN)
    return caller.user


def require_api_scope(
    caller: Caller = Depends(resolve_caller),
) -> CurrentUser:
    """FastAPI dependency: require read access to the ``/api/*`` data routes.

    The caller must be an authenticated user of role ``readonly`` or above;
    an API key must additionally carry the ``api`` scope. This is the gate
    on search / facets / stats.

    Args:
        caller: The resolved caller (injected).

    Returns:
        The :class:`CurrentUser`.

    Raises:
        HTTPException: ``403`` when the role is below ``readonly`` (cannot
            happen for a valid user, but fails closed) or an API key lacks
            the ``api`` scope.
    """
    _enforce(caller, required_role="readonly", required_scope=SCOPE_API)
    return caller.user


def require_api_scope_member(
    caller: Caller = Depends(resolve_caller),
) -> CurrentUser:
    """FastAPI dependency: ``api`` scope plus a Member-or-above role.

    Gates the reconcile trigger — a write action that, per spec §4.3, needs
    role Member+. An API key still needs the ``api`` scope.

    Args:
        caller: The resolved caller (injected).

    Returns:
        The :class:`CurrentUser`.

    Raises:
        HTTPException: ``403`` for a Read-only caller, or an API key without
            the ``api`` scope.
    """
    _enforce(caller, required_role="member", required_scope=SCOPE_API)
    return caller.user


def require_mcp_scope(
    caller: Caller = Depends(resolve_caller),
) -> CurrentUser:
    """FastAPI dependency: require ``mcp`` access.

    The MCP ASGI middleware does its own check (it is not a FastAPI route);
    this dependency exists for any FastAPI-routed MCP-adjacent endpoint and
    for symmetry. An API key must carry the ``mcp`` scope.

    Args:
        caller: The resolved caller (injected).

    Returns:
        The :class:`CurrentUser`.

    Raises:
        HTTPException: ``403`` when an API key lacks the ``mcp`` scope.
    """
    _enforce(caller, required_role="readonly", required_scope=SCOPE_MCP)
    return caller.user


def require_key_management(
    caller: Caller = Depends(resolve_caller),
) -> CurrentUser:
    """FastAPI dependency: gate the API-key management endpoints.

    Per spec §4.3 a Member manages their own keys and an Admin manages all.
    A cookie caller needs role Member or above. An API-key caller must
    additionally hold the ``admin`` scope — managing credentials through a
    non-admin key would be a privilege-escalation hole.

    The *ownership* check (own key vs any key) is left to the route handler,
    which has the key row; this dependency only enforces the role/scope bar
    to even reach the endpoint.

    Args:
        caller: The resolved caller (injected).

    Returns:
        The :class:`CurrentUser`.

    Raises:
        HTTPException: ``403`` for a Read-only caller, or an API key without
            the ``admin`` scope.
    """
    _enforce(caller, required_role="member", required_scope=SCOPE_ADMIN)
    return caller.user


def _refresh_last_seen(
    app_db: sqlite3.Connection, cookie_token: str | None
) -> None:
    """Refresh the session's ``last_seen_at`` when it is stale.

    A no-op when *cookie_token* is absent or the stored timestamp is recent,
    so this is a database write only roughly once every five minutes per
    session.

    Args:
        app_db: The per-request ``app.db`` connection.
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


def _touch_api_key(
    app_db: sqlite3.Connection, api_key_id: int, last_used_at: str | None
) -> None:
    """Record a use of the API key when its usage stats are stale.

    A no-op when the stored ``last_used_at`` is recent (see
    :func:`search.api_keys.should_touch`), so authentication is a database
    write only roughly once a minute per key.

    Args:
        app_db: The per-request ``app.db`` connection.
        api_key_id: The id of the key that authenticated the request.
        last_used_at: The key's stored ``last_used_at`` (or ``None``).
    """
    if should_touch(last_used_at):
        key_store.touch(
            app_db,
            api_key_id,
            used_at=datetime.now(timezone.utc).isoformat(),
        )
