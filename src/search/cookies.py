"""Session-cookie issuance for the search server's login handshake.

A thin layer over :mod:`search.auth`: :func:`issue_token` stamps a signed
session token with the current wall clock, and :func:`set_session_cookie`
writes it onto a response with every required security flag.  Both the login
route handler and the app factory's wiring use these, so the cookie attributes
have exactly one home (``CODE_GUIDELINES.md`` §1.3).

Depends on: starlette/fastapi Response, search.auth, common.config.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal, cast

from search.auth import (
    SESSION_COOKIE_NAME,
    cookie_attributes,
    issue_session_token,
)

if TYPE_CHECKING:
    from fastapi import Response

    from common.config import Settings


def issue_token(settings: Settings) -> str:
    """Issue a signed session token using the current wall clock.

    Args:
        settings: Application settings; ``SEARCH_API_KEY`` signs the token and
            ``SEARCH_SESSION_TTL`` sets its lifetime.

    Returns:
        The signed, URL-safe session token string.
    """
    return issue_session_token(
        settings.SEARCH_API_KEY,
        ttl_seconds=settings.SEARCH_SESSION_TTL,
        now=time.time(),
    )


def set_session_cookie(
    response: Response, token: str, settings: Settings
) -> None:
    """Set the signed session cookie on *response* with all security flags.

    Delegates every cookie attribute to :func:`search.auth.cookie_attributes`
    so that function is the single source of truth for HttpOnly, Secure,
    SameSite, Path, and Max-Age.  Each value is extracted individually with an
    explicit cast so mypy can verify the types match ``Response.set_cookie``'s
    signature precisely — no ``# type: ignore`` required.

    Args:
        response: The response object to set the cookie on.
        token: The signed session token string.
        settings: Application settings; passed to ``cookie_attributes`` for
            ``SEARCH_SESSION_TTL``.
    """
    attrs = cookie_attributes(settings)
    # The dict is keyed to match Response.set_cookie exactly; each value is
    # narrowed to the concrete type that key always carries (see
    # search.auth.cookie_attributes for the canonical definitions).
    # cast() is used because the return type is dict[str, object] — the values
    # are always the types below, but mypy cannot prove it from the signature.
    max_age: int = cast(int, attrs["max_age"])
    path: str = cast(str, attrs["path"])
    httponly: bool = cast(bool, attrs["httponly"])
    secure: bool = cast(bool, attrs["secure"])
    # rationale: cookie_attributes() always returns _COOKIE_SAMESITE ("strict"),
    # a Literal["strict"] constant — but the dict value type is `object`, so
    # mypy cannot narrow it without a cast. A TypedDict return on
    # cookie_attributes() would remove the need, but exports an extra public
    # type from search.auth that no other caller requires.
    samesite: Literal["strict", "lax", "none"] = cast(
        Literal["strict", "lax", "none"], attrs["samesite"]
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path=path,
        httponly=httponly,
        secure=secure,
        samesite=samesite,
    )
