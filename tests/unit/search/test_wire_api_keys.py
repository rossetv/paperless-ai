"""Tests for the API-key wire models in search.wire.

Covers: CreateApiKeyRequest validates name/scopes/optional expiry; a bad
scope or empty name raises pydantic.ValidationError; UpdateApiKeyRequest
accepts a partial body and rejects a bad scope; to_api_key_response maps an
ApiKey to the JSON shape (with the resolved owner name) and never leaks
key_hash; ApiKeyEnvelope wraps one key; CreatedApiKeyResponse carries the
one-time raw secret.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from search.wire import (
    ApiKeyEnvelope,
    ApiKeyResponse,
    CreateApiKeyRequest,
    CreatedApiKeyResponse,
    UpdateApiKeyRequest,
    to_api_key_response,
)

# The owner display name the handler would resolve from the users table and
# pass to to_api_key_response — the dataclass row carries only the owner id.
OWNER_NAME = "Sam Owner"


def _make_api_key(**overrides):
    """Build an appdb.api_keys.ApiKey with sensible defaults.

    The dataclass keeps its DB column name ``owner_user_id``; the wire layer
    renames it to ``owner_id`` and adds the separately-resolved owner name.
    """
    from appdb.api_keys import ApiKey

    fields = {
        "id": 5,
        "key_hash": "deadbeef" * 8,
        "key_prefix": "sk-pls-AbC1",
        "name": "CI token",
        "owner_user_id": 2,
        "scopes": "api,mcp",
        "created_at": "2026-05-01T00:00:00+00:00",
        "expires_at": None,
        "last_used_at": "2026-05-10T09:00:00+00:00",
        "revoked_at": None,
        "request_count": 42,
    }
    fields.update(overrides)
    return ApiKey(**fields)


def test_create_request_accepts_a_valid_body() -> None:
    body = CreateApiKeyRequest(name="CI", scopes=["api", "mcp"])
    assert body.name == "CI"
    assert body.scopes == ["api", "mcp"]
    assert body.expires_at is None


def test_create_request_accepts_an_explicit_expiry() -> None:
    body = CreateApiKeyRequest(
        name="CI", scopes=["api"], expires_at="2027-01-01T00:00:00+00:00"
    )
    assert body.expires_at == "2027-01-01T00:00:00+00:00"


def test_create_request_rejects_an_empty_name() -> None:
    with pytest.raises(ValidationError):
        CreateApiKeyRequest(name="", scopes=["api"])


def test_create_request_rejects_an_overlong_name() -> None:
    with pytest.raises(ValidationError):
        CreateApiKeyRequest(name="x" * 101, scopes=["api"])


def test_create_request_rejects_an_empty_scope_list() -> None:
    with pytest.raises(ValidationError):
        CreateApiKeyRequest(name="CI", scopes=[])


def test_create_request_rejects_an_unknown_scope() -> None:
    with pytest.raises(ValidationError):
        CreateApiKeyRequest(name="CI", scopes=["api", "superuser"])


def test_to_api_key_response_maps_the_public_fields() -> None:
    response = to_api_key_response(_make_api_key(), owner_name=OWNER_NAME)
    assert isinstance(response, ApiKeyResponse)
    assert response.id == 5
    assert response.name == "CI token"
    assert response.key_prefix == "sk-pls-AbC1"
    assert response.owner_id == 2
    assert response.owner_name == OWNER_NAME
    assert response.scopes == ["api", "mcp"]
    assert response.created_at == "2026-05-01T00:00:00+00:00"
    assert response.last_used_at == "2026-05-10T09:00:00+00:00"
    assert response.revoked_at is None
    assert response.request_count == 42


def test_to_api_key_response_never_leaks_the_key_hash() -> None:
    """The SHA-256 hash must never appear in the serialised key."""
    response = to_api_key_response(_make_api_key(), owner_name=OWNER_NAME)
    assert not hasattr(response, "key_hash")
    assert "deadbeef" not in response.model_dump_json()


def test_to_api_key_response_reports_a_revoked_key() -> None:
    response = to_api_key_response(
        _make_api_key(revoked_at="2026-05-20T00:00:00+00:00"),
        owner_name=OWNER_NAME,
    )
    assert response.revoked_at == "2026-05-20T00:00:00+00:00"


def test_created_response_carries_the_one_time_raw_secret() -> None:
    response = CreatedApiKeyResponse(
        secret="sk-pls-the-full-raw-key",
        api_key=to_api_key_response(_make_api_key(), owner_name=OWNER_NAME),
    )
    assert response.secret == "sk-pls-the-full-raw-key"
    assert response.api_key.id == 5


def test_update_request_accepts_a_partial_body() -> None:
    """Every field is optional — a name-only edit is valid."""
    body = UpdateApiKeyRequest(name="renamed")
    assert body.name == "renamed"
    assert body.scopes is None
    assert body.expires_at is None


def test_update_request_accepts_an_empty_body() -> None:
    """An empty PATCH body is valid (a no-op edit); the handler re-reads."""
    body = UpdateApiKeyRequest()
    assert body.name is None
    assert body.scopes is None
    assert body.expires_at is None


def test_update_request_accepts_scopes_and_expiry() -> None:
    body = UpdateApiKeyRequest(
        scopes=["api", "mcp"], expires_at="2027-01-01T00:00:00+00:00"
    )
    assert body.scopes == ["api", "mcp"]
    assert body.expires_at == "2027-01-01T00:00:00+00:00"


def test_update_request_rejects_an_empty_name() -> None:
    """A supplied name must still be non-empty — omit it to leave it."""
    with pytest.raises(ValidationError):
        UpdateApiKeyRequest(name="")


def test_update_request_rejects_an_unknown_scope() -> None:
    with pytest.raises(ValidationError):
        UpdateApiKeyRequest(scopes=["api", "superuser"])


def test_update_request_rejects_an_empty_scope_list() -> None:
    """A supplied scope list cannot be empty — a scope-less key is useless."""
    with pytest.raises(ValidationError):
        UpdateApiKeyRequest(scopes=[])


def test_api_key_envelope_wraps_one_key() -> None:
    envelope = ApiKeyEnvelope(
        api_key=to_api_key_response(_make_api_key(), owner_name=OWNER_NAME)
    )
    assert envelope.api_key.id == 5
    assert not hasattr(envelope, "secret")
