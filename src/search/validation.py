"""Account-field validation for the search server's HTTP request models.

The single home for the field rules the API contract pins (web-redesign §4.6
and the Wave 1 API contract): username length and charset, password minimum
length, the role enum, the optional display-name length, and a basic email
shape. The Pydantic request models in :mod:`search.wire` call these from
their field validators, so the setup, login, and user-CRUD endpoints all
enforce one definition.

Each validator returns the value unchanged on success and raises
``ValueError`` with a human-readable message on failure. Pydantic turns that
``ValueError`` into a 422 response automatically.

Allowed deps: stdlib (re) only. Forbidden: FastAPI, sqlite3, store, daemons.
"""

from __future__ import annotations

import re

# Username: 3-64 characters, letters/digits/dot/underscore/hyphen only.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_USERNAME_MIN = 3
_USERNAME_MAX = 64

# Password: a minimum length only (no composition rules — length beats them).
_PASSWORD_MIN = 8

# Display name: an optional free-text field, length-capped.
_DISPLAY_NAME_MAX = 120

# The three human-account roles (web-redesign §4.3).
_ROLES = frozenset({"admin", "member", "readonly"})

# A deliberately permissive email check: one "@", a non-empty local part, and
# a domain containing a dot. Full RFC 5322 validation is not the goal — this
# only rejects obvious nonsense (spec: "basic email shape").
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_username(username: str) -> str:
    """Return *username* if it satisfies the contract, else raise ``ValueError``.

    The rule: 3-64 characters, each a letter, digit, dot, underscore, or
    hyphen.

    Args:
        username: The candidate username.

    Raises:
        ValueError: The username is too short, too long, or contains a
            disallowed character.
    """
    if not _USERNAME_MIN <= len(username) <= _USERNAME_MAX:
        raise ValueError(
            f"username must be between {_USERNAME_MIN} and "
            f"{_USERNAME_MAX} characters"
        )
    if _USERNAME_RE.fullmatch(username) is None:
        raise ValueError(
            "username may contain only letters, digits, '.', '_' and '-'"
        )
    return username


def validate_password(password: str) -> str:
    """Return *password* if it is long enough, else raise ``ValueError``.

    The rule: at least 8 characters. No composition rules are imposed —
    length is the more useful constraint.

    Args:
        password: The candidate password.

    Raises:
        ValueError: The password is shorter than the minimum.
    """
    if len(password) < _PASSWORD_MIN:
        raise ValueError(
            f"password must be at least {_PASSWORD_MIN} characters"
        )
    return password


def validate_role(role: str) -> str:
    """Return *role* if it is one of the three known roles, else raise.

    Args:
        role: The candidate role string.

    Raises:
        ValueError: *role* is not ``admin``, ``member``, or ``readonly``.
    """
    if role not in _ROLES:
        raise ValueError(
            "role must be one of: admin, member, readonly"
        )
    return role


def validate_display_name(display_name: str | None) -> str | None:
    """Return *display_name* if valid, else raise ``ValueError``.

    ``None`` is valid — the field is optional. A present value must be at
    most 120 characters.

    Args:
        display_name: The candidate display name, or ``None``.

    Raises:
        ValueError: A present *display_name* exceeds the length cap.
    """
    if display_name is None:
        return None
    if len(display_name) > _DISPLAY_NAME_MAX:
        raise ValueError(
            f"display_name must be at most {_DISPLAY_NAME_MAX} characters"
        )
    return display_name


def validate_email(email: str | None) -> str | None:
    """Return *email* if it has a plausible shape, else raise ``ValueError``.

    ``None`` is valid — the field is optional. A present value must match a
    basic ``local@domain.tld`` shape; this is not full RFC validation.

    Args:
        email: The candidate email address, or ``None``.

    Raises:
        ValueError: A present *email* does not look like an email address.
    """
    if email is None:
        return None
    if _EMAIL_RE.fullmatch(email) is None:
        raise ValueError("email is not a valid email address")
    return email
