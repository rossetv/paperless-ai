"""Tests for search.validation — account-field validation rules.

Covers the API-contract limits: username length and charset; password
minimum length; role enum; display_name optional length; email optional
basic shape. Each validator returns the cleaned value or raises ValueError.
"""

from __future__ import annotations

import pytest

from search.validation import (
    validate_display_name,
    validate_email,
    validate_password,
    validate_role,
    validate_username,
)


@pytest.mark.parametrize("name", ["abc", "alice", "a_b-c.d", "User-99", "x" * 64])
def test_validate_username_accepts_valid_names(name: str) -> None:
    assert validate_username(name) == name


@pytest.mark.parametrize(
    "name",
    ["ab", "", "x" * 65, "has space", "bad!", "emoji😀", "tab\tname"],
)
def test_validate_username_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError):
        validate_username(name)


@pytest.mark.parametrize("password", ["12345678", "x" * 8, "a long passphrase"])
def test_validate_password_accepts_eight_or_more_chars(password: str) -> None:
    assert validate_password(password) == password


@pytest.mark.parametrize("password", ["", "short", "1234567"])
def test_validate_password_rejects_under_eight_chars(password: str) -> None:
    with pytest.raises(ValueError):
        validate_password(password)


@pytest.mark.parametrize("role", ["admin", "member", "readonly"])
def test_validate_role_accepts_known_roles(role: str) -> None:
    assert validate_role(role) == role


@pytest.mark.parametrize("role", ["", "superuser", "Admin", "service"])
def test_validate_role_rejects_unknown_roles(role: str) -> None:
    with pytest.raises(ValueError):
        validate_role(role)


def test_validate_display_name_accepts_none() -> None:
    assert validate_display_name(None) is None


def test_validate_display_name_accepts_a_normal_name() -> None:
    assert validate_display_name("Alice Smith") == "Alice Smith"


def test_validate_display_name_accepts_120_chars() -> None:
    value = "x" * 120
    assert validate_display_name(value) == value


def test_validate_display_name_rejects_over_120_chars() -> None:
    with pytest.raises(ValueError):
        validate_display_name("x" * 121)


def test_validate_email_accepts_none() -> None:
    assert validate_email(None) is None


@pytest.mark.parametrize(
    "email", ["a@b.co", "alice@example.com", "user.name+tag@sub.example.org"]
)
def test_validate_email_accepts_basic_shapes(email: str) -> None:
    assert validate_email(email) == email


@pytest.mark.parametrize(
    "email", ["", "no-at-sign", "@nodomain.com", "user@", "user@nodot", "a b@c.com"]
)
def test_validate_email_rejects_bad_shapes(email: str) -> None:
    with pytest.raises(ValueError):
        validate_email(email)
