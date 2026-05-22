"""The API-key management ``/api`` router for the search server (§5, §4.3).

Four endpoints, factored out of ``search/routes.py`` so each router file
stays focused:

- ``GET    /api/api-keys``      — list keys. A Member sees their own; an
  admin sees every key.
- ``POST   /api/api-keys``      — create a key owned by the caller; returns
  the full raw key **exactly once**.
- ``PATCH  /api/api-keys/{id}`` — edit a key's name/scopes/expiry.
  **Owner-only** — even an admin cannot edit another user's key. Returns the
  updated key, never a secret.
- ``DELETE /api/api-keys/{id}`` — revoke a key. The owner revokes their own;
  an admin revokes any.

Handlers are thin: they delegate to ``appdb.api_keys``, ``appdb.users``,
``search.api_keys`` (raw-key generation, hashing, scope serialisation) and
the ``search.wire`` mappers. The role/scope bar is the
``require_key_management`` dependency; the per-row ownership check (own key
vs any key — and, for ``PATCH``, owner-only) is done in the handlers, which
hold the row.

The wire ``ApiKeyResponse`` carries ``owner_name`` — the owning user's
display name — but the ``api_keys`` row stores only the owner's id. The
handlers therefore look the owner up in the ``users`` table and pass the
name to ``search.wire.to_api_key_response``.

The raw key is generated, hashed and stored here; only its SHA-256 and
display prefix are persisted. The full key is returned once in the
``POST`` response and is then unrecoverable.

The ``app.db`` connection is opened **per request** by the
:func:`~search.deps.get_app_db` dependency and closed when the request ends —
a ``sqlite3.Connection`` is never shared across requests, mirroring
``account_routes`` and ``document_routes``.

Allowed deps: fastapi, sqlite3, structlog, appdb, search (api_keys, deps,
sessions, wire).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response

from appdb import api_keys as key_store
from appdb import users as user_store
from appdb.api_keys import ApiKey, DuplicateKeyHashError
from search.api_keys import (
    generate_raw_key,
    hash_key,
    key_display_prefix,
    serialise_scopes,
)
from search.deps import get_app_db, require_key_management
from search.sessions import CurrentUser
from search.wire import (
    ApiKeyEnvelope,
    ApiKeyListResponse,
    CreateApiKeyRequest,
    CreatedApiKeyResponse,
    UpdateApiKeyRequest,
    to_api_key_response,
)

log = structlog.get_logger(__name__)


def build_api_key_router() -> APIRouter:
    """Build the API-key management ``/api`` router (web-redesign §5).

    The handlers reach the ``app.db`` connection through the per-request
    :func:`~search.deps.get_app_db` dependency and the caller's identity
    through :func:`~search.deps.require_key_management`.

    Returns:
        A configured :class:`~fastapi.APIRouter`.
    """
    router = APIRouter()

    @router.get("/api/api-keys")
    async def list_api_keys(
        app_db: sqlite3.Connection = Depends(get_app_db),
        caller: CurrentUser = Depends(require_key_management),
    ) -> ApiKeyListResponse:
        """List API keys: own keys for a Member, every key for an admin."""
        return _list_api_keys(app_db, caller)

    @router.post("/api/api-keys", status_code=201)
    async def create_api_key(
        body: CreateApiKeyRequest,
        app_db: sqlite3.Connection = Depends(get_app_db),
        caller: CurrentUser = Depends(require_key_management),
    ) -> CreatedApiKeyResponse:
        """Create a key owned by the caller; return the one-time full key."""
        return _create_api_key(body, app_db, caller)

    @router.patch("/api/api-keys/{api_key_id}")
    async def update_api_key(
        api_key_id: int,
        body: UpdateApiKeyRequest,
        app_db: sqlite3.Connection = Depends(get_app_db),
        caller: CurrentUser = Depends(require_key_management),
    ) -> ApiKeyEnvelope:
        """Edit a key (owner-only). 404 unknown; 403 not yours."""
        return _update_api_key(api_key_id, body, app_db, caller)

    @router.delete("/api/api-keys/{api_key_id}", status_code=204)
    async def delete_api_key(
        api_key_id: int,
        app_db: sqlite3.Connection = Depends(get_app_db),
        caller: CurrentUser = Depends(require_key_management),
    ) -> Response:
        """Revoke a key (owner or admin). 404 unknown; 403 not yours."""
        return _delete_api_key(api_key_id, app_db, caller)

    return router


# ---------------------------------------------------------------------------
# Handler bodies — free of FastAPI routing, easy to read and test
# ---------------------------------------------------------------------------


def _is_admin(caller: CurrentUser) -> bool:
    """Return whether *caller* has the admin role."""
    return caller.role == "admin"


def _owner_name(app_db: sqlite3.Connection, owner_user_id: int) -> str:
    """Resolve a key owner's display name from the ``users`` table.

    The ``api_keys`` row stores only the owner's id, but the wire
    :class:`~search.wire.ApiKeyResponse` carries ``owner_name`` too. This
    looks the owner up and returns their display name, falling back to the
    username when no display name is set. A missing owner cannot normally
    occur — ``owner_user_id`` is an ``ON DELETE CASCADE`` foreign key — but
    if the row is gone it returns a stable placeholder rather than raising.

    Args:
        app_db: The per-request ``app.db`` connection.
        owner_user_id: The owning user's id (the key row's ``owner_user_id``).

    Returns:
        The owner's display name, their username, or ``"(unknown)"``.
    """
    owner = user_store.get_by_id(app_db, owner_user_id)
    if owner is None:
        return "(unknown)"
    return owner.display_name or owner.username


def _list_api_keys(
    app_db: sqlite3.Connection, caller: CurrentUser
) -> ApiKeyListResponse:
    """list-handler body: every key for an admin, own keys otherwise.

    Each key is mapped to its wire shape with the owner's display name
    resolved from the ``users`` table.
    """
    if _is_admin(caller):
        keys = key_store.list_all(app_db)
    else:
        keys = key_store.list_for_user(app_db, caller.id)
    return ApiKeyListResponse(
        keys=[
            to_api_key_response(k, _owner_name(app_db, k.owner_user_id))
            for k in keys
        ]
    )


def _create_api_key(
    body: CreateApiKeyRequest, app_db: sqlite3.Connection, caller: CurrentUser
) -> CreatedApiKeyResponse:
    """create-handler body: mint, hash, store, return the one-time key.

    The key is always owned by *caller* — a Member cannot mint a key for
    someone else, and an admin minting through this endpoint also owns the
    result (admin-on-behalf-of is out of scope for Wave 3).
    """
    # serialise_scopes re-validates the scope list (wire.py validated it
    # too) and yields the canonical comma-separated stored form.
    try:
        scopes = serialise_scopes(body.scopes)
    except ValueError as exc:
        # wire.py should have caught this; treat a slip as a 422-shaped 400.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw_key = generate_raw_key()
    try:
        created = key_store.create(
            app_db,
            key_hash=hash_key(raw_key),
            key_prefix=key_display_prefix(raw_key),
            name=body.name,
            owner_user_id=caller.id,
            scopes=scopes,
            expires_at=body.expires_at,
        )
    except DuplicateKeyHashError as exc:
        # A SHA-256 collision on a 256-bit random key is astronomically
        # unlikely; surface it as a 500-shaped retryable error rather than
        # pretend success.
        log.error("search.api_key_hash_collision")
        raise HTTPException(
            status_code=500,
            detail="Could not generate a unique key — please retry.",
        ) from exc

    log.info(
        "search.api_key_created",
        api_key_id=created.id,
        owner_user_id=caller.id,
    )
    # The full raw key is returned here, as `secret`, and never again. The
    # key is owned by the caller, so its owner_name is the caller's display
    # name — resolved (like the list handler) from the users table.
    return CreatedApiKeyResponse(
        api_key=to_api_key_response(
            created, _owner_name(app_db, created.owner_user_id)
        ),
        secret=raw_key,
    )


def _update_api_key(
    api_key_id: int,
    body: UpdateApiKeyRequest,
    app_db: sqlite3.Connection,
    caller: CurrentUser,
) -> ApiKeyEnvelope:
    """update-handler body: existence + owner-only check, then a partial edit.

    Editing a key is **owner-only** — unlike revoke, an admin may *not* edit
    another user's key (re-scoping or renaming a credential is the owner's
    call). Only ``name``, ``scopes`` and ``expires_at`` are mutable.

    Pydantic's ``model_fields_set`` tells which fields the client actually
    sent, so an absent field is left untouched while an explicit
    ``expires_at: null`` clears the expiry — the two are indistinguishable
    from the parsed value alone.
    """
    record: ApiKey | None = key_store.get_by_id(app_db, api_key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found.")

    # Owner-only — an admin cannot edit someone else's key (they may only
    # view and revoke it). This is stricter than the DELETE handler.
    if record.owner_user_id != caller.id:
        log.warning(
            "search.api_key_update_forbidden",
            api_key_id=api_key_id,
            actor_user_id=caller.id,
        )
        raise HTTPException(
            status_code=403,
            detail="You may only edit your own API keys.",
        )

    # Build the partial update from only the fields the client sent.
    sent = body.model_fields_set
    changes: dict[str, object] = {}
    if "name" in sent and body.name is not None:
        changes["name"] = body.name
    if "scopes" in sent and body.scopes is not None:
        # serialise_scopes re-validates (wire.py validated it too) and yields
        # the canonical comma-separated stored form.
        try:
            changes["scopes"] = serialise_scopes(body.scopes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "expires_at" in sent:
        # Present-and-null clears the expiry; present-with-a-value sets it.
        changes["expires_at"] = body.expires_at

    updated = key_store.update(app_db, api_key_id, **changes)
    # The row existed at the top of this handler and update() re-reads it on
    # the same connection — it cannot have vanished.
    assert updated is not None
    log.info(
        "search.api_key_updated",
        api_key_id=api_key_id,
        actor_user_id=caller.id,
        fields=sorted(changes),
    )
    return ApiKeyEnvelope(
        api_key=to_api_key_response(
            updated, _owner_name(app_db, updated.owner_user_id)
        )
    )


def _delete_api_key(
    api_key_id: int, app_db: sqlite3.Connection, caller: CurrentUser
) -> Response:
    """delete-handler body: existence + ownership check, then revoke.

    Revocation is a soft delete (``revoked_at`` is set); the row stays so the
    UI keeps the key's history. A non-admin may only revoke a key they own.
    """
    record: ApiKey | None = key_store.get_by_id(app_db, api_key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found.")

    if not _is_admin(caller) and record.owner_user_id != caller.id:
        # Do not leak whether the key exists to a non-owner — but it is
        # already past the existence check, so 403 is the honest answer and
        # the UI never shows a non-owner another user's key id anyway.
        log.warning(
            "search.api_key_delete_forbidden",
            api_key_id=api_key_id,
            actor_user_id=caller.id,
        )
        raise HTTPException(
            status_code=403,
            detail="You may only revoke your own API keys.",
        )

    key_store.revoke(
        app_db,
        api_key_id,
        revoked_at=datetime.now(timezone.utc).isoformat(),
    )
    log.info(
        "search.api_key_revoked",
        api_key_id=api_key_id,
        actor_user_id=caller.id,
    )
    return Response(status_code=204)
