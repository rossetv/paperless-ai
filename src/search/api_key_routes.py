"""The API-key management ``/api`` router.

- ``GET    /api/api-keys``      — list keys. A Member sees their own; an
  admin sees every key.
- ``POST   /api/api-keys``      — create a key owned by the caller; returns
  the full raw key **exactly once**.
- ``PATCH  /api/api-keys/{id}`` — edit a key's name/scopes/expiry.
  **Owner-only** — even an admin cannot edit another user's key. Returns the
  updated key, never a secret.
- ``DELETE /api/api-keys/{id}`` — revoke a key. The owner revokes their own;
  an admin revokes any.

The role/scope bar is the ``require_key_management`` dependency; the per-row
ownership check is done in the handlers, which hold the row. Only the key's
SHA-256 and display prefix are stored, so the full key is unrecoverable after
the ``POST`` response.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Response

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
from search.errors import RowVanishedError
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

# The app database stores ids as SQLite INTEGER; a larger one can name no row.
_MAX_ROW_ID = 2**63 - 1


def build_api_key_router() -> APIRouter:
    """Build the API-key management ``/api`` router."""
    router = APIRouter()

    @router.get("/api/api-keys")
    def list_api_keys(
        app_db: sqlite3.Connection = Depends(get_app_db),
        caller: CurrentUser = Depends(require_key_management),
    ) -> ApiKeyListResponse:
        """List API keys: own keys for a Member, every key for an admin."""
        return _list_api_keys(app_db, caller)

    @router.post("/api/api-keys", status_code=201)
    def create_api_key(
        body: CreateApiKeyRequest,
        app_db: sqlite3.Connection = Depends(get_app_db),
        caller: CurrentUser = Depends(require_key_management),
    ) -> CreatedApiKeyResponse:
        """Create a key owned by the caller; return the one-time full key."""
        return _create_api_key(body, app_db, caller)

    @router.patch("/api/api-keys/{api_key_id}")
    def update_api_key(
        api_key_id: Annotated[int, Path(le=_MAX_ROW_ID)],
        body: UpdateApiKeyRequest,
        app_db: sqlite3.Connection = Depends(get_app_db),
        caller: CurrentUser = Depends(require_key_management),
    ) -> ApiKeyEnvelope:
        """Edit a key (owner-only). 404 when unknown or not yours."""
        return _update_api_key(api_key_id, body, app_db, caller)

    @router.delete("/api/api-keys/{api_key_id}", status_code=204)
    def delete_api_key(
        api_key_id: Annotated[int, Path(le=_MAX_ROW_ID)],
        app_db: sqlite3.Connection = Depends(get_app_db),
        caller: CurrentUser = Depends(require_key_management),
    ) -> Response:
        """Revoke a key (owner or admin). 404 when unknown or not yours."""
        return _delete_api_key(api_key_id, app_db, caller)

    return router


def _owner_name(app_db: sqlite3.Connection, owner_user_id: int) -> str:
    """Return the owner's display name, else username, else ``"(unknown)"``.

    A missing owner should not happen (the foreign key cascades on delete), but
    a placeholder beats raising.
    """
    owner = user_store.get_by_id(app_db, owner_user_id)
    if owner is None:
        return "(unknown)"
    return owner.display_name or owner.username


def _list_api_keys(
    app_db: sqlite3.Connection, caller: CurrentUser
) -> ApiKeyListResponse:
    """Return every key for an admin, own keys otherwise."""
    if caller.role == "admin":
        keys = key_store.list_all(app_db)
    else:
        keys = key_store.list_for_user(app_db, caller.id)
    return ApiKeyListResponse(
        keys=[
            to_api_key_response(k, _owner_name(app_db, k.owner_user_id)) for k in keys
        ]
    )


def _create_api_key(
    body: CreateApiKeyRequest, app_db: sqlite3.Connection, caller: CurrentUser
) -> CreatedApiKeyResponse:
    """Mint, hash, and store a key owned by *caller*; return the one-time key."""
    try:
        scopes = serialise_scopes(body.scopes)
    except ValueError as exc:
        # The wire model validates scopes too; this only catches a slip.
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
        # Astronomically unlikely for a 256-bit random key; fail rather than
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
    # The only time the raw key is ever returned.
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
    """Apply a partial edit to a key the caller owns.

    Unlike revoke, an admin may not edit another user's key: re-scoping or
    renaming a credential is the owner's call. ``model_fields_set`` separates
    an absent field (left alone) from an explicit ``expires_at: null`` (clears
    the expiry).
    """
    record: ApiKey | None = key_store.get_by_id(app_db, api_key_id)
    # 404, not 403, for a non-owner, so key ids cannot be enumerated.
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found.")
    if record.owner_user_id != caller.id:
        log.warning(
            "search.api_key_update_forbidden",
            api_key_id=api_key_id,
            actor_user_id=caller.id,
        )
        raise HTTPException(status_code=404, detail="API key not found.")

    sent = body.model_fields_set
    changes: dict[str, object] = {}
    if "name" in sent and body.name is not None:
        changes["name"] = body.name
    if "scopes" in sent and body.scopes is not None:
        try:
            changes["scopes"] = serialise_scopes(body.scopes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "expires_at" in sent:
        changes["expires_at"] = body.expires_at

    updated = key_store.update(app_db, api_key_id, **changes)
    # A raise rather than an assert, which `python -O` strips.
    if updated is None:
        raise RowVanishedError(f"api key {api_key_id} vanished during an update")
    log.info(
        "search.api_key_updated",
        api_key_id=api_key_id,
        actor_user_id=caller.id,
        fields=sorted(changes),
    )
    return ApiKeyEnvelope(
        api_key=to_api_key_response(updated, _owner_name(app_db, updated.owner_user_id))
    )


def _delete_api_key(
    api_key_id: int, app_db: sqlite3.Connection, caller: CurrentUser
) -> Response:
    """Revoke a key; a non-admin may only revoke their own.

    Revocation is a soft delete (``revoked_at`` is set), so the UI keeps the
    key's history.
    """
    record: ApiKey | None = key_store.get_by_id(app_db, api_key_id)
    # 404, not 403, for a non-owner, so key ids cannot be enumerated.
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found.")
    if caller.role != "admin" and record.owner_user_id != caller.id:
        log.warning(
            "search.api_key_delete_forbidden",
            api_key_id=api_key_id,
            actor_user_id=caller.id,
        )
        raise HTTPException(status_code=404, detail="API key not found.")

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
