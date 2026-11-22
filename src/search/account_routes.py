"""The account-management ``/api`` router: setup, login/logout, and users.

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

Every handler is a plain ``def`` (not ``async def``): the bodies call blocking
SQLite and argon2id hashing, so FastAPI runs them in the threadpool, off the
event loop.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from appdb import users as user_store
from appdb.passwords import hash_password
from common.config import current_settings
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
from search.login_throttle import build_attempt_key, get_login_throttle
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
    to_user_response,
)
from store import StoreError

if TYPE_CHECKING:
    from common.config import Settings
    from store.reader import StoreReader

log = structlog.get_logger(__name__)


def _remember_ttl(app_db_path: str, startup: Settings) -> int:
    """The live ``SEARCH_SESSION_TTL``, or the startup value if settings can't load."""
    try:
        return current_settings(app_db_path).SEARCH_SESSION_TTL
    except Exception:
        log.warning("session_ttl_settings_unavailable", exc_info=True)
        return startup.SEARCH_SESSION_TTL


def build_account_router(settings: Settings, store_reader: StoreReader) -> APIRouter:
    """Build the account ``/api`` router.

    The "keep me signed in" cookie reads ``SEARCH_SESSION_TTL`` from the live
    settings on each login, so a Settings save applies without a restart.
    *settings* supplies the lifetime if the live settings cannot be loaded;
    *store_reader* backs ``GET /api/stats/public``.
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
        """Create the first admin, gated by the setup token.

        Raises 409 once any user exists, 403 on a bad setup token.
        """
        return _setup(body, app_db, state.setup_state)

    @router.post("/api/auth/login")
    def login(
        body: LoginRequest,
        request: Request,
        response: Response,
        app_db: sqlite3.Connection = Depends(get_app_db),
        state: AppState = Depends(get_app_state),
    ) -> UserEnvelope:
        """Verify credentials and set the session cookie.

        401 on bad credentials; 403 when the account is suspended; 429 when
        either the (client IP, username) pair or the username alone has too many
        recent failures.
        """
        return _login(
            body,
            request,
            response,
            app_db,
            remember_ttl_seconds=_remember_ttl(state.app_db_path, settings),
        )

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
        request: Request,
        app_db: sqlite3.Connection = Depends(get_app_db),
        admin: CurrentUser = Depends(require_admin),
    ) -> UserEnvelope:
        """Partially update a user (admin only).

        A password reset ends the user's sessions, all but the caller's own
        when admins reset their own password. 404 when the user is unknown; 409
        when a guard rejects the change.
        """
        return _update_user(
            user_id,
            body,
            admin,
            app_db,
            actor_session_token=request.cookies.get(SESSION_COOKIE_NAME),
        )

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


def _setup(
    body: SetupRequest, app_db: sqlite3.Connection, setup_state: SetupState
) -> UserEnvelope:
    """Check the setup token and create the first admin.

    Two concurrent setups can both pass ``is_setup_needed``; the race is closed
    by ``create_initial_admin``, a single ``INSERT … SELECT … WHERE NOT EXISTS``
    that SQLite runs atomically, so the loser inserts nothing and gets ``None``.
    """
    # Cheap pre-check so every request after setup skips the INSERT.
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
    *,
    remember_ttl_seconds: int,
) -> UserEnvelope:
    """Throttle, authenticate, open a session, and set the cookie.

    The throttle denies with 429 before any argon2 work. It keeps two counters:
    per-(client IP, username), and per-username so an attack that rotates
    X-Forwarded-For (attacker-controlled while SEARCH_FORWARDED_ALLOW_IPS is
    "*") is still bounded. A success clears both.
    """
    client_ip = request.client.host if request.client else None
    attempt_key = build_attempt_key(client_ip=client_ip, username=body.username)
    throttle = get_login_throttle()
    if not throttle.begin_attempt(attempt_key):
        # Generic message, no account hints.
        log.warning("search.login_throttled", username=body.username)
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(throttle.retry_after_seconds(attempt_key))},
        )

    try:
        user = authenticate(app_db, body.username, body.password)
    except BaseException:
        throttle.abandon_attempt(attempt_key)
        raise
    if user is None:
        # Wrong username or password — one message for both, so the response
        # does not reveal whether the username exists. Count the failure toward
        # the brute-force throttle.
        throttle.record_failure(attempt_key)
        log.warning("search.login_rejected", username=body.username)
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    # The password was correct: clear any earlier failure history for this key
    # so a legitimate user is never throttled by their own past typos — even on
    # the suspended path below, where the credential itself was valid.
    throttle.record_success(attempt_key)
    if user.status != "active":
        log.warning("search.login_suspended", username=body.username)
        raise HTTPException(status_code=403, detail="This account is suspended.")

    ttl = cookie_ttl_seconds(
        remember=body.remember, remember_ttl_seconds=remember_ttl_seconds
    )
    issued = begin_session(
        app_db,
        user_id=user.id,
        ttl_seconds=ttl,
        user_agent=request.headers.get("user-agent"),
        # uvicorn runs with proxy_headers=True, so this is the client IP from
        # the trusted X-Forwarded-For header, not the reverse proxy's.
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
    """Re-read the full user row; ``get_current_user`` yields only the slim one."""
    row = user_store.get_by_id(app_db, user.id)
    if row is None:
        # The session resolved a moment ago but the row is gone — treat it
        # as unauthenticated rather than 500.
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserEnvelope(user=to_user_response(row))


def _stats_public(store_reader: StoreReader) -> PublicStatsResponse:
    """Return the splash counts; a store failure gives zeroes, not a 500."""
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
    """Hash the password and insert the user; 409 when the username is taken."""
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
    *,
    actor_session_token: str | None,
) -> UserEnvelope:
    """404 on an unknown user, else apply the guarded atomic update.

    The existence check sits outside the guard's transaction on purpose: it only
    decides 404-vs-proceed.
    """
    if user_store.get_by_id(app_db, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")

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
            actor_session_token=actor_session_token,
        )
    except GuardError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log.info("search.user_updated", user_id=user_id)
    return UserEnvelope(user=to_user_response(updated))


def _delete_user(
    user_id: int, actor: CurrentUser, app_db: sqlite3.Connection
) -> Response:
    """404 on an unknown user, else apply the guarded atomic delete."""
    if user_store.get_by_id(app_db, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")

    # The sessions foreign key cascades, so this also revokes their sessions.
    try:
        apply_guarded_delete(app_db, target_id=user_id, actor_id=actor.id)
    except GuardError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log.info("search.user_deleted", user_id=user_id)
    return Response(status_code=204)
