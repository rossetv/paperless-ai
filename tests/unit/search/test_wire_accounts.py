"""Tests for the account wire models in search.wire.

Covers: LoginRequest validates username/password and defaults remember to
False; SetupRequest / CreateUserRequest enforce the field rules; an invalid
field raises pydantic.ValidationError; UpdateUserRequest accepts a partial
body; to_user_response maps a User to the JSON shape and omits password_hash.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from search.wire import (
    CreateUserRequest,
    LoginRequest,
    SetupRequest,
    UpdateUserRequest,
    to_user_response,
)


def _make_user(**overrides):
    """Build an appdb.users.User with sensible defaults."""
    from appdb.users import User

    fields = {
        "id": 1,
        "username": "alice",
        "password_hash": "secret-hash",
        "display_name": "Alice",
        "email": "alice@example.com",
        "role": "admin",
        "status": "active",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-02T00:00:00+00:00",
        "last_login_at": "2026-01-03T00:00:00+00:00",
        "password_changed_at": "2026-01-01T00:00:00+00:00",
    }
    fields.update(overrides)
    return User(**fields)


def test_login_request_accepts_a_valid_body() -> None:
    body = LoginRequest(username="alice", password="password1", remember=True)
    assert body.username == "alice"
    assert body.remember is True


def test_login_request_remember_defaults_to_false() -> None:
    body = LoginRequest(username="alice", password="password1")
    assert body.remember is False


def test_login_request_rejects_a_short_username() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(username="ab", password="password1")


def test_login_request_rejects_a_short_password() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(username="alice", password="short")


def test_setup_request_accepts_a_valid_body() -> None:
    body = SetupRequest(token="setup-token", username="admin", password="password1")
    assert body.token == "setup-token"
    assert body.username == "admin"


def test_setup_request_rejects_a_bad_username() -> None:
    with pytest.raises(ValidationError):
        SetupRequest(token="t", username="bad name", password="password1")


def test_create_user_request_accepts_a_full_body() -> None:
    body = CreateUserRequest(
        username="bob",
        password="password1",
        display_name="Bob",
        email="bob@example.com",
        role="member",
    )
    assert body.role == "member"
    assert body.email == "bob@example.com"


def test_create_user_request_rejects_a_bad_role() -> None:
    with pytest.raises(ValidationError):
        CreateUserRequest(username="bob", password="password1", role="superuser")


def test_create_user_request_rejects_a_bad_email() -> None:
    with pytest.raises(ValidationError):
        CreateUserRequest(
            username="bob",
            password="password1",
            role="member",
            email="not-an-email",
        )


def test_update_user_request_accepts_an_empty_body() -> None:
    body = UpdateUserRequest()
    assert body.display_name is None
    assert body.role is None


def test_update_user_request_accepts_a_partial_body() -> None:
    body = UpdateUserRequest(role="admin")
    assert body.role == "admin"
    assert body.status is None


def test_update_user_request_rejects_a_bad_status() -> None:
    with pytest.raises(ValidationError):
        UpdateUserRequest(status="banned")


def test_to_user_response_maps_the_public_fields() -> None:
    response = to_user_response(_make_user())
    assert response.id == 1
    assert response.username == "alice"
    assert response.display_name == "Alice"
    assert response.email == "alice@example.com"
    assert response.role == "admin"
    assert response.status == "active"
    assert response.created_at == "2026-01-01T00:00:00+00:00"
    assert response.last_login_at == "2026-01-03T00:00:00+00:00"


def test_to_user_response_omits_the_password_hash() -> None:
    """The password hash must never appear in the serialised user."""
    response = to_user_response(_make_user())
    assert "secret-hash" not in response.model_dump_json()
    assert not hasattr(response, "password_hash")


def test_to_user_response_handles_null_optionals() -> None:
    response = to_user_response(
        _make_user(display_name=None, email=None, last_login_at=None)
    )
    assert response.display_name is None
    assert response.email is None
    assert response.last_login_at is None
