"""The account-management ``/api`` router for the search server (§4.6).

Every Wave 1 account endpoint lives here, factored out of ``search/routes.py``
so each router file stays focused and under the size ceiling:

- ``GET  /api/setup/status``  — public; is first-run setup still needed?
- ``POST /api/setup``         — setup-token gated; create the first admin.
- ``POST /api/auth/login``    — public; username/password → session cookie.
- ``POST /api/auth/logout``   — session; destroy the current session.
- ``GET  /api/auth/me``       — session; the current user.
- ``GET  /api/users``         — admin; list users.
- ``POST /api/users``         — admin; create a user.
- ``PATCH  /api/users/{id}``  — admin; partial update.
- ``DELETE /api/users/{id}``  — admin; delete a user.
- ``GET  /api/stats/public``  — public; minimal splash counts.

The handlers are thin: they delegate to ``appdb``, ``search.sessions``,
``search.setup``, ``search.accounts``, and the ``search.wire`` mappers, all
of which are unit-tested in isolation. Errors use FastAPI's ``{"detail": ...}``
shape.

Every handler is a plain ``def`` (not ``async def``): the bodies call blocking
SQLite and blocking argon2id password hashing, so FastAPI runs them in the
threadpool — keeping that work off the event loop. Each takes its ``app.db``
connection from the per-request :func:`~search.deps.get_app_db` dependency.

Allowed deps: fastapi, structlog, appdb, search (sessions, setup, accounts,
deps, appstate, cookies, wire), store (reader).
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from appdb import users as user_store
from appdb.passwords import hash_password
from appdb.users import Role, UsernameTakenError, UserStatus
from search.accounts import (
    GuardError,
    apply_guarded_delete,
    apply_guarded_update,
)
from search.appstate import AppState, get_app_state
from search.auth import SESSION_COOKIE_NAME
from search.cookies import clear_session_cookie, set_session_cookie
from search.deps import get_app_db, get_current_user, require_admin
from search.passwords_login import authenticate
from search.sessions import CurrentUser, begin_session, cookie_ttl_seconds, end_session
from search.setup import SetupState, is_setup_needed, verify_setup_token
from search.wire import (
    CreateUserRequest,
    LoginRequest,
    PublicStatsResponse,
    SetupRequest,
    SetupStatusResponse,
    UpdateUserRequest,
    UserEnvelope,
    UserListResponse,
    UserResponse,
    to_user_response,
)
from store import StoreError

if TYPE_CHECKING:
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

# The cookie name appears only via the helpers in search.cookies; no literal
# here. The session-cookie security flags are owned there too.


def build_account_router(store_reader: StoreReader) -> APIRouter:
    """Build the account ``/api`` router (web-redesign §4.6).

    The handlers close over *store_reader* (for the public stats endpoint)
    and reach everything else — the per-request ``app.db`` connection, the
    setup state, the legacy key — through FastAPI dependencies.

    # rationale: 60+ executable lines — the body is ten route declarations,
    # one per account endpoint, each an irreducible decorator + signature +
    # delegation. Splitting the registrations across helpers would scatter one
    # flat table of routes without making any of it clearer.

    Args:
        store_reader: The read-side store, backing ``GET /api/stats/public``.

    Returns:
        A configured :class:`~fastapi.APIRouter`.
    """
    router = APIRouter()

    @router.get("/api/setup/status")
    def setup_status(
        app_db: sqlite3.Connection = Depends(get_app_db),
    ) -> SetupStatusResponse:
        """Report whether first-run setup is still required (public)."""
        return SetupStatusResponse(needed=is_setup_needed(app_db))

    @router.post("/api/setup", status_code=201)
    def setup(
        body: SetupRequest,
        app_db: sqlite3.Connection = Depends(get_app_db),
        state: AppState = Depends(get_app_state),
    ) -> UserEnvelope:
        """Create the first admin, gated by the setup token (§4.5).

        Raises 409 once any user exists, 403 on a bad setup token.
        """
        return _setup(body, app_db, state.setup_state)

    @router.post("/api/auth/login")
    def login(
        body: LoginRequest,
        request: Request,
        response: Response,
        app_db: sqlite3.Connection = Depends(get_app_db),
    ) -> UserEnvelope:
        """Verify credentials and set the session cookie (§4.4).

        401 on bad credentials; 403 when the account is suspended.
        """
        return _login(body, request, response, app_db)

    @router.post("/api/auth/logout", status_code=204)
    def logout(
        request: Request,
        response: Response,
        app_db: sqlite3.Connection = Depends(get_app_db),
        _user: CurrentUser = Depends(get_current_user),
    ) -> Response:
        """Destroy the current session and clear the cookie."""
        end_session(app_db, request.cookies.get(SESSION_COOKIE_NAME))
        clear_session_cookie(response)
        return Response(status_code=204)

    @router.get("/api/auth/me")
    def auth_me(
        app_db: sqlite3.Connection = Depends(get_app_db),
        user: CurrentUser = Depends(get_current_user),
    ) -> UserEnvelope:
        """Return the current user (401 when unauthenticated)."""
        return _auth_me(user, app_db)

    @router.get("/api/stats/public")
    def stats_public() -> PublicStatsResponse:
        """Return the minimal splash counts (public)."""
        return _stats_public(store_reader)

    @router.get("/api/users")
    def list_users(
        app_db: sqlite3.Connection = Depends(get_app_db),
        _admin: CurrentUser = Depends(require_admin),
    ) -> UserListResponse:
        """List every user (admin only)."""
        users = user_store.list_all(app_db)
        return UserListResponse(users=[to_user_response(u) for u in users])

    @router.post("/api/users", status_code=201)
    def create_user(
        body: CreateUserRequest,
        app_db: sqlite3.Connection = Depends(get_app_db),
        _admin: CurrentUser = Depends(require_admin),
    ) -> UserEnvelope:
        """Create a user (admin only). 409 when the username is taken."""
        return _create_user(body, app_db)

    @router.patch("/api/users/{user_id}")
    def update_user(
        user_id: int,
        body: UpdateUserRequest,
        app_db: sqlite3.Connection = Depends(get_app_db),
        admin: CurrentUser = Depends(require_admin),
    ) -> UserEnvelope:
        """Partially update a user (admin only).

        404 when the user is unknown; 409 when a guard rejects the change.
        """
        return _update_user(user_id, body, admin, app_db)

    @router.delete("/api/users/{user_id}", status_code=204)
    def delete_user(
        user_id: int,
        app_db: sqlite3.Connection = Depends(get_app_db),
        admin: CurrentUser = Depends(require_admin),
    ) -> Response:
        """Delete a user (admin only).

        404 when the user is unknown; 409 when a guard rejects the deletion.
        """
        return _delete_user(user_id, admin, app_db)

    return router


# ---------------------------------------------------------------------------
# Handler bodies — free of FastAPI routing, easy to read and test
# ---------------------------------------------------------------------------


def _setup(
    body: SetupRequest, app_db: sqlite3.Connection, setup_state: SetupState
) -> UserEnvelope:
    """Setup-handler body: token check, first-admin creation (§4.5).

    The TOCTOU race (two concurrent ``POST /api/setup`` both passing
    ``is_setup_needed`` before either inserts) is closed by
    ``user_store.create_initial_admin``, which executes a single
    ``INSERT … SELECT … WHERE NOT EXISTS`` statement: SQLite evaluates the
    sub-query and the insert atomically under its write lock, so the second
    concurrent caller inserts zero rows and receives ``None``. That argument
    holds because each request now uses its own ``app.db`` connection (see
    :func:`~search.deps.get_app_db`); an atomic statement is per-connection
    atomic, and the two racing setups are on distinct connections.
    """
    # Fast pre-flight check — avoids the INSERT on every request after setup.
    if not is_setup_needed(app_db):
        raise HTTPException(status_code=409, detail="Setup has already been completed.")
    if not verify_setup_token(setup_state, body.token):
        log.warning("search.setup_rejected")
        raise HTTPException(status_code=403, detail="Invalid setup token.")

    user = user_store.create_initial_admin(
        app_db,
        username=body.username,
        password_hash=hash_password(body.password),
    )
    if user is None:
        raise HTTPException(status_code=409, detail="Setup has already been completed.")

    # Setup is complete: drop the token so it can never be reused.
    setup_state.token = None
    log.info("search.setup_completed", user_id=user.id)
    return UserEnvelope(user=to_user_response(user))


def _login(
    body: LoginRequest,
    request: Request,
    response: Response,
    app_db: sqlite3.Connection,
) -> UserEnvelope:
    """Login-handler body: authenticate, open a session, set the cookie."""
    user = authenticate(app_db, body.username, body.password)
    if user is None:
        # Wrong username or password — one message for both, so the response
        # does not reveal whether the username exists.
        log.warning("search.login_rejected", username=body.username)
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if user.status != "active":
        log.warning("search.login_suspended", username=body.username)
        raise HTTPException(status_code=403, detail="This account is suspended.")

    ttl = cookie_ttl_seconds(remember=body.remember)
    issued = begin_session(
        app_db,
        user_id=user.id,
        ttl_seconds=ttl,
        user_agent=request.headers.get("user-agent"),
        # request.client.host is the real client IP: the server runs uvicorn
        # with proxy_headers=True (see search.api.main), so behind the
        # nginx/Cloudflare deployment Starlette rewrites request.client from
        # the trusted X-Forwarded-For header rather than the reverse-proxy
        # socket peer.
        ip=request.client.host if request.client else None,
    )
    set_session_cookie(
        response,
        token=issued.token,
        max_age=ttl,
        secure=request.url.scheme == "https",
    )
    user_store.record_login(app_db, user.id)
    log.info("search.login_ok", user_id=user.id)
    return UserEnvelope(user=to_user_response(user))


def _auth_me(user: CurrentUser, app_db: sqlite3.Connection) -> UserEnvelope:
    """auth/me-handler body: re-read the full user for the response.

    ``get_current_user`` yields the slim :class:`CurrentUser`; the response
    contract is the full user object, so the row is re-read here.
    """
    row = user_store.get_by_id(app_db, user.id)
    if row is None:
        # The session resolved a moment ago but the row is gone — treat it
        # as unauthenticated rather than 500.
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserEnvelope(user=to_user_response(row))


def _stats_public(store_reader: StoreReader) -> PublicStatsResponse:
    """stats/public-handler body: minimal splash counts.

    Any store failure degrades to zeroes rather than a 500 — the splash
    numbers are cosmetic (spec §4.7: "if it fails, the numbers are omitted").
    """
    try:
        stats = store_reader.get_stats()
        return PublicStatsResponse(
            document_count=stats.document_count,
            chunk_count=stats.chunk_count,
        )
    except StoreError:
        log.info("search.stats_public_unavailable")
        return PublicStatsResponse(document_count=0, chunk_count=0)


def _create_user(body: CreateUserRequest, app_db: sqlite3.Connection) -> UserEnvelope:
    """create-user-handler body: hash the password, insert, map."""
    try:
        user = user_store.create(
            app_db,
            username=body.username,
            password_hash=hash_password(body.password),
            # The wire model's `validate_role` field validator has already
            # rejected anything outside the Role enum, so this cast is safe.
            role=cast(Role, body.role),
            display_name=body.display_name,
            email=body.email,
        )
    except UsernameTakenError as exc:
        raise HTTPException(
            status_code=409, detail="That username is already taken."
        ) from exc
    log.info("search.user_created", user_id=user.id)
    return UserEnvelope(user=to_user_response(user))


def _update_user(
    user_id: int,
    body: UpdateUserRequest,
    actor: CurrentUser,
    app_db: sqlite3.Connection,
) -> UserEnvelope:
    """update-user-handler body: existence check, then guarded atomic update.

    The 404 existence check and the guarded write are deliberately separate:
    the guard read and the ``UPDATE`` are made atomic inside
    :func:`~search.accounts.apply_guarded_update`, while the existence check
    only decides 404-vs-proceed and need not share that transaction.
    """
    if user_store.get_by_id(app_db, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")

    # A password reset is hashed before it reaches the store.
    password_hash = hash_password(body.password) if body.password is not None else None
    # `validate_role` and `validate_status` on the wire model have already
    # rejected anything outside the Role / UserStatus enums; the casts narrow
    # the validated `str | None` fields to the literal types appdb expects.
    try:
        updated = apply_guarded_update(
            app_db,
            target_id=user_id,
            actor_id=actor.id,
            display_name=body.display_name,
            email=body.email,
            role=cast("Role | None", body.role),
            status=cast("UserStatus | None", body.status),
            password_hash=password_hash,
        )
    except GuardError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log.info("search.user_updated", user_id=user_id)
    return UserEnvelope(user=to_user_response(updated))


def _delete_user(
    user_id: int, actor: CurrentUser, app_db: sqlite3.Connection
) -> Response:
    """delete-user-handler body: existence check, then guarded atomic delete."""
    if user_store.get_by_id(app_db, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")

    # The sessions foreign key cascades, so deleting the user also revokes
    # every session they hold. The guard and the DELETE are atomic.
    try:
        apply_guarded_delete(app_db, target_id=user_id, actor_id=actor.id)
    except GuardError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log.info("search.user_deleted", user_id=user_id)
    return Response(status_code=204)
