"""Pydantic wire models for authentication, setup, and user accounts.

The request/response shapes for the login, setup, and user-management endpoints
(web-redesign §4.6) plus the converter from the internal user dataclass. A
boundary module of the :mod:`search.wire` package: field validators delegate to
:mod:`search.validation` so the rules live in one place
(``CODE_GUIDELINES.md`` §5.6).

Allowed deps: pydantic, search.validation, appdb.users (User, type-only).
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from typing import Annotated, TYPE_CHECKING

from pydantic import AfterValidator, BaseModel, field_validator

from search.validation import (
    validate_display_name,
    validate_email,
    validate_password,
    validate_role,
    validate_username,
)

if TYPE_CHECKING:
    from appdb.users import User

# ---------------------------------------------------------------------------
# Reusable annotated field types — one validator definition per rule.
# ---------------------------------------------------------------------------

_Username = Annotated[str, AfterValidator(validate_username)]
_Password = Annotated[str, AfterValidator(validate_password)]
_Role = Annotated[str, AfterValidator(validate_role)]
_DisplayName = Annotated[str | None, AfterValidator(validate_display_name)]
_Email = Annotated[str | None, AfterValidator(validate_email)]


def _validate_optional_role(value: str | None) -> str | None:
    return None if value is None else validate_role(value)


def _validate_optional_password(value: str | None) -> str | None:
    return None if value is None else validate_password(value)


_OptionalRole = Annotated[str | None, AfterValidator(_validate_optional_role)]
_OptionalPassword = Annotated[str | None, AfterValidator(_validate_optional_password)]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Body for ``POST /api/auth/login`` — username/password credentials.

    Replaces the Wave 0 ``{api_key}`` body. ``remember`` selects the session
    lifetime: ticked → seven days, un-ticked → eight hours (spec §4.4).
    """

    username: _Username
    password: _Password
    remember: bool = False


class SetupRequest(BaseModel):
    """Body for ``POST /api/setup`` — the setup token plus the first admin."""

    token: str
    username: _Username
    password: _Password


class CreateUserRequest(BaseModel):
    """Body for ``POST /api/users`` — a new account created by an admin."""

    username: _Username
    password: _Password
    role: _Role
    display_name: _DisplayName = None
    email: _Email = None


class UpdateUserRequest(BaseModel):
    """Body for ``PATCH /api/users/{id}`` — a partial account update.

    Every field is optional; only those present are applied. ``status``
    accepts ``active`` or ``suspended``; ``password`` triggers a reset.
    """

    display_name: _DisplayName = None
    email: _Email = None
    role: _OptionalRole = None
    status: str | None = None
    password: _OptionalPassword = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: str | None) -> str | None:
        """Reject a status outside active/suspended when one is supplied."""
        if value is not None and value not in ("active", "suspended"):
            raise ValueError("status must be 'active' or 'suspended'")
        return value


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    """A user as returned to the browser — never carries the password hash."""

    id: int
    username: str
    display_name: str | None
    email: str | None
    role: str
    status: str
    created_at: str
    last_login_at: str | None


class UserEnvelope(BaseModel):
    """The ``{"user": User}`` envelope for single-user responses."""

    user: UserResponse


class UserListResponse(BaseModel):
    """The ``{"users": [User, ...]}`` envelope for ``GET /api/users``."""

    users: list[UserResponse]


class SetupStatusResponse(BaseModel):
    """Response body for ``GET /api/setup/status``."""

    needed: bool


def to_user_response(user: User) -> UserResponse:
    """Convert an :class:`appdb.users.User` to its public wire shape.

    The single boundary mapper from the internal user dataclass to the HTTP
    response. It deliberately drops ``password_hash``, ``updated_at`` and
    ``password_changed_at`` — none of which belongs in an API response.

    Args:
        user: The internal user dataclass.

    Returns:
        A :class:`UserResponse` safe to serialise to JSON.
    """
    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )
