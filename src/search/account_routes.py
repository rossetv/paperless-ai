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

Allowed deps: fastapi, structlog, appdb, search (sessions, setup, accounts,
deps, appstate, cookies, wire), store (reader).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from appdb import users as user_store
from appdb.passwords import hash_password
from appdb.users import Role, UsernameTakenError, UserStatus
from search.accounts import GuardError, guard_delete, guard_update
from search.appstate import AppState, get_app_state
from search.cookies import clear_session_cookie, set_session_cookie
from search.deps import get_current_user, require_admin
from search.passwords_login import authenticate
from search.sessions import CurrentUser, begin_session, cookie_ttl_seconds, end_session
from search.setup import is_setup_needed, verify_setup_token
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

if TYPE_CHECKING:
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

# The cookie name appears only via the helpers in search.cookies; no literal
# here. The session-cookie security flags are owned there too.


def build_account_router(store_reader: StoreReader) -> APIRouter:
    """Build the account ``/api`` router (web-redesign §4.6).

    The handlers close over *store_reader* (for the public stats endpoint)
    and reach everything else — the ``app.db`` connection, the setup state,
    the legacy key — through the :class:`~search.appstate.AppState` dependency.

    Args:
        store_reader: The read-side store, backing ``GET /api/stats/public``.

    Returns:
        A configured :class:`~fastapi.APIRouter`.
    """
    router = APIRouter()

    @router.get("/api/setup/status")
    async def setup_status(
        state: AppState = Depends(get_app_state),
    ) -> SetupStatusResponse:
        """Report whether first-run setup is still required (public)."""
        return SetupStatusResponse(needed=is_setup_needed(state.app_db))

    @router.post("/api/setup", status_code=201)
    async def setup(
        body: SetupRequest,
        state: AppState = Depends(get_app_state),
    ) -> UserEnvelope:
        """Create the first admin, gated by the setup token (§4.5).

        Raises 409 once any user exists, 403 on a bad setup token.
        """
        return _setup(body, state)

    @router.post("/api/auth/login")
    async def login(
        body: LoginRequest,
        request: Request,
        response: Response,
        state: AppState = Depends(get_app_state),
    ) -> UserEnvelope:
        """Verify credentials and set the session cookie (§4.4).

        401 on bad credentials; 403 when the account is suspended.
        """
        return _login(body, request, response, state)

    @router.post("/api/auth/logout", status_code=204)
    async def logout(
        request: Request,
        response: Response,
        state: AppState = Depends(get_app_state),
        _user: CurrentUser = Depends(get_current_user),
    ) -> Response:
        """Destroy the current session and clear the cookie."""
        from search.auth import SESSION_COOKIE_NAME

        end_session(state.app_db, request.cookies.get(SESSION_COOKIE_NAME))
        clear_session_cookie(response)
        return Response(status_code=204)

    @router.get("/api/auth/me")
    async def auth_me(
        state: AppState = Depends(get_app_state),
        user: CurrentUser = Depends(get_current_user),
    ) -> UserEnvelope:
        """Return the current user (401 when unauthenticated)."""
        return _auth_me(user, state)

    @router.get("/api/stats/public")
    async def stats_public() -> PublicStatsResponse:
        """Return the minimal splash counts (public)."""
        return _stats_public(store_reader)

    @router.get("/api/users")
    async def list_users(
        state: AppState = Depends(get_app_state),
        _admin: CurrentUser = Depends(require_admin),
    ) -> UserListResponse:
        """List every user (admin only)."""
        users = user_store.list_all(state.app_db)
        return UserListResponse(
            users=[to_user_response(u) for u in users]
        )

    @router.post("/api/users", status_code=201)
    async def create_user(
        body: CreateUserRequest,
        state: AppState = Depends(get_app_state),
        _admin: CurrentUser = Depends(require_admin),
    ) -> UserEnvelope:
        """Create a user (admin only). 409 when the username is taken."""
        return _create_user(body, state)

    @router.patch("/api/users/{user_id}")
    async def update_user(
        user_id: int,
        body: UpdateUserRequest,
        state: AppState = Depends(get_app_state),
        admin: CurrentUser = Depends(require_admin),
    ) -> UserEnvelope:
        """Partially update a user (admin only).

        404 when the user is unknown; 409 when a guard rejects the change.
        """
        return _update_user(user_id, body, admin, state)

    @router.delete("/api/users/{user_id}", status_code=204)
    async def delete_user(
        user_id: int,
        state: AppState = Depends(get_app_state),
        admin: CurrentUser = Depends(require_admin),
    ) -> Response:
        """Delete a user (admin only).

        404 when the user is unknown; 409 when a guard rejects the deletion.
        """
        return _delete_user(user_id, admin, state)

    return router


# ---------------------------------------------------------------------------
# Handler bodies — free of FastAPI routing, easy to read and test
# ---------------------------------------------------------------------------


def _setup(body: SetupRequest, state: AppState) -> UserEnvelope:
    """Setup-handler body: token check, first-admin creation (§4.5).

    The TOCTOU race (two concurrent ``POST /api/setup`` both passing
    ``is_setup_needed`` before either inserts) is closed by
    ``user_store.create_initial_admin``, which executes a single
    ``INSERT … SELECT … WHERE NOT EXISTS`` statement. SQLite evaluates the
    sub-query and the insert atomically under its write lock, so the second
    concurrent caller inserts zero rows and receives ``None`` — no manual
    transaction management or ``isolation_level`` dependency required.
    """
    # Fast pre-flight check — avoids the INSERT on every request after setup.
    if not is_setup_needed(state.app_db):
        raise HTTPException(
            status_code=409, detail="Setup has already been completed."
        )
    if not verify_setup_token(state.setup_state, body.token):
        log.warning("search.setup_rejected")
        raise HTTPException(status_code=403, detail="Invalid setup token.")

    user = user_store.create_initial_admin(
        state.app_db,
        username=body.username,
        password_hash=hash_password(body.password),
    )
    if user is None:
        raise HTTPException(
            status_code=409, detail="Setup has already been completed."
        )

    # Setup is complete: drop the token so it can never be reused.
    state.setup_state.token = None
    log.info("search.setup_completed", user_id=user.id)
    return UserEnvelope(user=to_user_response(user))


def _login(
    body: LoginRequest, request: Request, response: Response, state: AppState
) -> UserEnvelope:
    """Login-handler body: authenticate, open a session, set the cookie."""
    user = authenticate(state.app_db, body.username, body.password)
    if user is None:
        # Wrong username or password — one message for both, so the response
        # does not reveal whether the username exists.
        log.warning("search.login_rejected", username=body.username)
        raise HTTPException(
            status_code=401, detail="Invalid username or password."
        )
    if user.status != "active":
        log.warning("search.login_suspended", username=body.username)
        raise HTTPException(
            status_code=403, detail="This account is suspended."
        )

    ttl = cookie_ttl_seconds(remember=body.remember)
    issued = begin_session(
        state.app_db,
        user_id=user.id,
        ttl_seconds=ttl,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    set_session_cookie(
        response,
        token=issued.token,
        max_age=ttl,
        secure=request.url.scheme == "https",
    )
    user_store.record_login(state.app_db, user.id)
    log.info("search.login_ok", user_id=user.id)
    return UserEnvelope(user=to_user_response(user))


def _auth_me(user: CurrentUser, state: AppState) -> UserEnvelope:
    """auth/me-handler body: re-read the full user for the response.

    ``get_current_user`` yields the slim :class:`CurrentUser`; the response
    contract is the full user object, so the row is re-read here. The legacy
    API-key caller has no user row (id 0) — it is reported as a synthetic
    admin so the frontend has a consistent shape.
    """
    from search.wire import UserResponse

    if user.id == 0:
        # The legacy SEARCH_API_KEY caller — no user row exists.
        return UserEnvelope(
            user=UserResponse(
                id=0,
                username=user.username,
                display_name="Legacy API key",
                email=None,
                role=user.role,
                status="active",
                created_at="",
                last_login_at=None,
            )
        )
    row = user_store.get_by_id(state.app_db, user.id)
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
    from store import StoreError

    try:
        stats = store_reader.get_stats()
        return PublicStatsResponse(
            document_count=stats.document_count,
            chunk_count=stats.chunk_count,
        )
    except StoreError:
        log.info("search.stats_public_unavailable")
        return PublicStatsResponse(document_count=0, chunk_count=0)


def _create_user(body: CreateUserRequest, state: AppState) -> UserEnvelope:
    """create-user-handler body: hash the password, insert, map."""
    try:
        user = user_store.create(
            state.app_db,
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
    state: AppState,
) -> UserEnvelope:
    """update-user-handler body: existence check, guards, partial update."""
    if user_store.get_by_id(state.app_db, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")

    try:
        guard_update(
            state.app_db,
            target_id=user_id,
            actor_id=actor.id,
            new_role=body.role,
            new_status=body.status,
        )
    except GuardError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # A password reset is hashed before it reaches the store.
    password_hash = (
        hash_password(body.password) if body.password is not None else None
    )
    # `validate_role` and `validate_status` on the wire model have already
    # rejected anything outside the Role / UserStatus enums; the casts narrow
    # the validated `str | None` fields to the literal types appdb expects.
    updated = user_store.update(
        state.app_db,
        user_id,
        display_name=body.display_name,
        email=body.email,
        role=cast("Role | None", body.role),
        status=cast("UserStatus | None", body.status),
        password_hash=password_hash,
    )
    # The existence check above passed and we hold the only writer — the row
    # is still here.
    assert updated is not None

    # Suspending a user must revoke their access immediately: drop every
    # session they hold (spec §4.4).
    if body.status == "suspended":
        from appdb import sessions as session_store

        session_store.delete_for_user(state.app_db, user_id)

    log.info("search.user_updated", user_id=user_id)
    return UserEnvelope(user=to_user_response(updated))


def _delete_user(
    user_id: int, actor: CurrentUser, state: AppState
) -> Response:
    """delete-user-handler body: existence check, guards, delete."""
    if user_store.get_by_id(state.app_db, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")

    try:
        guard_delete(
            state.app_db, target_id=user_id, actor_id=actor.id
        )
    except GuardError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # The sessions foreign key cascades, so deleting the user also revokes
    # every session they hold.
    user_store.delete(state.app_db, user_id)
    log.info("search.user_deleted", user_id=user_id)
    return Response(status_code=204)
