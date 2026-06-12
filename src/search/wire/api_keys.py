"""Pydantic wire models for the API-key endpoints (web-redesign §5, Wave 3).

The request/response shapes for ``POST``/``PATCH``/``GET /api/api-keys`` plus the
converter from the persisted key dataclass. A boundary module of the
:mod:`search.wire` package; scope validation delegates to
:mod:`search.api_keys` — the single source of truth for the valid scope set
(``CODE_GUIDELINES.md`` §5.6, §1.3).

Allowed deps: pydantic, search.api_keys (scope constants), appdb.api_keys
    (ApiKey, type-only).
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from search.api_keys import _VALID_SCOPES as _VALID_API_KEY_SCOPES_SET

if TYPE_CHECKING:
    from appdb.api_keys import ApiKey


def _normalise_expires_at(value: str | None) -> str | None:
    """Validate and canonicalise a client-supplied ``expires_at`` string.

    ``None`` passes straight through — it is itself a meaningful value (the key
    never expires, or, on a ``PATCH``, "clear the expiry"). A present value
    must be a parseable ISO-8601 timestamp; an unparseable one is rejected with
    a ``ValueError`` (Pydantic turns this into a 422). A parseable but tz-naive
    value (e.g. ``"2099-01-01T00:00:00"``) is coerced to UTC, and the result is
    re-emitted as a canonical tz-aware UTC isoformat string. This means the
    stored expiry is always tz-aware, so :func:`search.api_keys._is_expired`
    can never trip the naive-vs-aware comparison that would otherwise brick the
    key on every presentation.

    A value in the past is **not** rejected — minting an already-expired key is
    a no-op the auth layer handles cleanly, not a malformed request.

    Shared by :class:`CreateApiKeyRequest` and :class:`UpdateApiKeyRequest`.
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
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat()


def _validate_scope_list(value: list[str]) -> list[str]:
    """Reject any scope outside the documented three.

    Delegates to :data:`search.api_keys._VALID_SCOPES` — the single source of
    truth — so a future scope addition only needs to be made in one place.
    Shared by :class:`CreateApiKeyRequest` and :class:`UpdateApiKeyRequest`.
    """
    unknown = set(value) - _VALID_API_KEY_SCOPES_SET
    if unknown:
        raise ValueError(f"unknown scope(s): {sorted(unknown)}")
    return value


class CreateApiKeyRequest(BaseModel):
    """The body of ``POST /api/api-keys`` — request a new key.

    Attributes:
        name: A human label, 1-100 characters.
        scopes: A non-empty list drawn from ``api``/``mcp``/``admin``.
        expires_at: An optional ISO-8601 expiry; omitted = never expires. A
            malformed value is rejected (422); a naive value is normalised to
            tz-aware UTC before storage.
    """

    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1)
    expires_at: str | None = None

    @field_validator("scopes")
    @classmethod
    def _scopes_are_valid(cls, value: list[str]) -> list[str]:
        """Reject any scope outside the documented three."""
        return _validate_scope_list(value)

    @field_validator("expires_at")
    @classmethod
    def _expires_at_is_valid(cls, value: str | None) -> str | None:
        """Reject a malformed expiry and normalise it to canonical UTC."""
        return _normalise_expires_at(value)


class UpdateApiKeyRequest(BaseModel):
    """The body of ``PATCH /api/api-keys/{id}`` — edit a key.

    Every field is optional: the caller sends only what it wants changed, and
    an absent field is left untouched (an empty body is a valid no-op edit).
    The immutable fields — the key itself, its owner, its prefix — can never
    be edited; only ``name``, ``scopes`` and ``expires_at`` are mutable.

    A *supplied* field still has to be valid: ``name`` cannot be empty and
    ``scopes`` cannot be empty or contain an unknown scope. To leave a field
    unchanged, omit it rather than sending an empty value.

    ``expires_at`` is special: ``None`` is itself a meaningful value — it
    means "this key never expires" — so the route handler distinguishes
    "clear the expiry" (``expires_at`` present and ``null``) from "leave the
    expiry unchanged" (``expires_at`` absent) via Pydantic's
    ``model_fields_set``, not the parsed value. See ``_update_api_key`` in
    Task W3B15.

    Attributes:
        name: A new human label, 1-100 characters, or ``None``/absent.
        scopes: A new non-empty scope list, or ``None``/absent.
        expires_at: A new ISO-8601 expiry, normalised to tz-aware UTC (a
            malformed value is rejected with a 422); ``null`` clears the
            expiry; absent leaves it unchanged.
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    scopes: list[str] | None = Field(default=None, min_length=1)
    expires_at: str | None = None

    @field_validator("scopes")
    @classmethod
    def _scopes_are_valid(cls, value: list[str] | None) -> list[str] | None:
        """Reject any scope outside the documented three, when supplied."""
        if value is None:
            return None
        return _validate_scope_list(value)

    @field_validator("expires_at")
    @classmethod
    def _expires_at_is_valid(cls, value: str | None) -> str | None:
        """Reject a malformed expiry and normalise it to canonical UTC.

        ``None`` is preserved (the route reads ``model_fields_set`` to tell
        "clear the expiry" from "leave it unchanged"), so this only validates
        and canonicalises a *supplied* non-null value.
        """
        return _normalise_expires_at(value)


class ApiKeyResponse(BaseModel):
    """One API key in an HTTP response — never carries the secret.

    Mirrors :class:`appdb.api_keys.ApiKey` minus ``key_hash``: the hash is a
    server-side secret and must never cross the wire. The dataclass column
    ``owner_user_id`` is exposed here as ``owner_id`` (the wire layer must
    not leak the DB column name), and ``owner_name`` — the owning user's
    display name — is added; it is resolved from the ``users`` table by the
    caller, since the key row itself only stores the owner's id.
    """

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
    """The body of ``PATCH /api/api-keys/{id}`` — one key, no secret.

    The updated key after an edit. Unlike :class:`CreatedApiKeyResponse` it
    carries **no** ``secret`` — editing a key never re-reveals it.
    """

    api_key: ApiKeyResponse


class CreatedApiKeyResponse(BaseModel):
    """The body of ``POST /api/api-keys`` — the one-time key reveal.

    ``secret`` is the full raw ``sk-pls-...`` key, returned **exactly once**
    at creation. No other endpoint ever returns it; the client must store it
    immediately. ``api_key`` is the persisted metadata (no secret).
    """

    api_key: ApiKeyResponse
    secret: str


def to_api_key_response(api_key: ApiKey, owner_name: str) -> ApiKeyResponse:
    """Map an :class:`appdb.api_keys.ApiKey` to its wire shape.

    Copies every public field and **omits** ``key_hash`` — the hash is a
    secret and never appears in a response. The stored comma-separated
    ``scopes`` string is split into a list for the JSON shape. The dataclass
    ``owner_user_id`` becomes the wire ``owner_id``; the owner's display name
    is not on the key row, so the caller resolves it from the ``users`` table
    and supplies it as *owner_name*.

    Args:
        api_key: The persisted key row.
        owner_name: The owning user's display name (the caller looks the
            owner up in the ``users`` table; falls back to the username when
            no display name is set).

    Returns:
        The :class:`ApiKeyResponse` for the HTTP layer.
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
