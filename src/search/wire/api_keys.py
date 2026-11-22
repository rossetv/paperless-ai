"""Wire models for the API-key endpoints.

Scope validation uses the scope set in :mod:`search.api_keys`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from search.api_keys import _VALID_SCOPES as _VALID_API_KEY_SCOPES_SET

if TYPE_CHECKING:
    from appdb.api_keys import ApiKey


def _normalise_expires_at(value: str | None) -> str | None:
    """Validate an ISO-8601 ``expires_at`` and re-emit it as tz-aware UTC.

    ``None`` passes through (never expires, or clear the expiry). A naive value
    is taken as UTC, so :func:`search.api_keys._is_expired` never compares
    naive with aware, which would raise on every use of the key. A past value
    is allowed: an already-expired key is harmless, not malformed.
    """
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        try:
            parsed = parsed.astimezone(timezone.utc)
        except OverflowError as exc:
            raise ValueError("expires_at is outside the supported date range") from exc
    return parsed.isoformat()


def _validate_scope_list(value: list[str]) -> list[str]:
    """Reject any scope outside :data:`search.api_keys._VALID_SCOPES`."""
    unknown = set(value) - _VALID_API_KEY_SCOPES_SET
    if unknown:
        raise ValueError(f"unknown scope(s): {sorted(unknown)}")
    return value


class CreateApiKeyRequest(BaseModel):
    """The body of ``POST /api/api-keys``.

    ``scopes`` is drawn from ``api``/``mcp``/``admin``; an omitted
    ``expires_at`` means the key never expires.
    """

    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=64)
    expires_at: str | None = None

    @field_validator("scopes")
    @classmethod
    def _scopes_are_valid(cls, value: list[str]) -> list[str]:
        """Reject an unknown scope."""
        return _validate_scope_list(value)

    @field_validator("expires_at")
    @classmethod
    def _expires_at_is_valid(cls, value: str | None) -> str | None:
        """Reject a malformed expiry and normalise it to canonical UTC."""
        return _normalise_expires_at(value)


class UpdateApiKeyRequest(BaseModel):
    """The body of ``PATCH /api/api-keys/{id}``: absent fields are unchanged.

    A supplied field must still be valid. For ``expires_at``, ``null`` means
    "never expires", so the route tells "clear the expiry" from "leave it
    unchanged" by ``model_fields_set``, not by the parsed value.
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    scopes: list[str] | None = Field(default=None, min_length=1, max_length=64)
    expires_at: str | None = None

    @field_validator("scopes")
    @classmethod
    def _scopes_are_valid(cls, value: list[str] | None) -> list[str] | None:
        """Reject an unknown scope, when supplied."""
        if value is None:
            return None
        return _validate_scope_list(value)

    @field_validator("expires_at")
    @classmethod
    def _expires_at_is_valid(cls, value: str | None) -> str | None:
        """Reject a malformed expiry and normalise it to canonical UTC."""
        return _normalise_expires_at(value)


class ApiKeyResponse(BaseModel):
    """One API key in an HTTP response, without its hash."""

    id: int
    name: str
    key_prefix: str
    owner_id: int
    owner_name: str
    scopes: list[str]
    created_at: str
    expires_at: str | None
    last_used_at: str | None
    revoked_at: str | None
    request_count: int


class ApiKeyListResponse(BaseModel):
    """The body of ``GET /api/api-keys`` — a list of keys."""

    keys: list[ApiKeyResponse]


class ApiKeyEnvelope(BaseModel):
    """The body of ``PATCH /api/api-keys/{id}``: editing never re-reveals the key."""

    api_key: ApiKeyResponse


class CreatedApiKeyResponse(BaseModel):
    """The body of ``POST /api/api-keys``.

    ``secret`` is the raw ``sk-pls-...`` key; no other response ever carries it.
    """

    api_key: ApiKeyResponse
    secret: str


def to_api_key_response(api_key: ApiKey, owner_name: str) -> ApiKeyResponse:
    """Map an :class:`appdb.api_keys.ApiKey` to its wire shape, minus the hash.

    The key row stores only the owner's id, so the caller supplies
    *owner_name*.
    """
    scope_list = [s for s in api_key.scopes.split(",") if s]
    return ApiKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        owner_id=api_key.owner_user_id,
        owner_name=owner_name,
        scopes=scope_list,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
        revoked_at=api_key.revoked_at,
        request_count=api_key.request_count,
    )
