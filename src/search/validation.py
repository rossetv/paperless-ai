"""Account-field validators used by the Pydantic request models in :mod:`search.wire`.

Each returns the value unchanged or raises ``ValueError``, which Pydantic turns
into a 422 response.
"""

from __future__ import annotations

import re

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_USERNAME_MIN = 3
_USERNAME_MAX = 64

# Length only, no composition rules: length is the more useful constraint.
_PASSWORD_MIN = 12

_DISPLAY_NAME_MAX = 120

_ROLES = frozenset({"admin", "member", "readonly"})

# A deliberately permissive email check: one "@", a non-empty local part, and
# a domain containing a dot. Full RFC 5322 validation is not the goal — this
# only rejects obvious nonsense.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_username(username: str) -> str:
    """Require 3-64 characters, each a letter, digit, dot, underscore, or hyphen."""
    if not _USERNAME_MIN <= len(username) <= _USERNAME_MAX:
        raise ValueError(
            f"username must be between {_USERNAME_MIN} and {_USERNAME_MAX} characters"
        )
    if _USERNAME_RE.fullmatch(username) is None:
        raise ValueError("username may contain only letters, digits, '.', '_' and '-'")
    return username


def validate_password(password: str) -> str:
    """Require at least 12 characters."""
    if len(password) < _PASSWORD_MIN:
        raise ValueError(f"password must be at least {_PASSWORD_MIN} characters")
    return password


def validate_role(role: str) -> str:
    """Require ``admin``, ``member``, or ``readonly``."""
    if role not in _ROLES:
        raise ValueError("role must be one of: admin, member, readonly")
    return role


def validate_display_name(display_name: str | None) -> str | None:
    """Allow ``None``; otherwise require at most 120 characters."""
    if display_name is None:
        return None
    if len(display_name) > _DISPLAY_NAME_MAX:
        raise ValueError(f"display_name must be at most {_DISPLAY_NAME_MAX} characters")
    return display_name


def validate_email(email: str | None) -> str | None:
    """Allow ``None``; otherwise require a basic ``local@domain.tld`` shape."""
    if email is None:
        return None
    if _EMAIL_RE.fullmatch(email) is None:
        raise ValueError("email is not a valid email address")
    return email
