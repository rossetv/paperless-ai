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
from typing import TYPE_CHECKING

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
    SameSite, Path, and Max-Age.  Explicit keyword arguments (rather than a
    ``**`` splat) keep mypy happy against ``Response.set_cookie``'s typed
    signature.

    Args:
        response: The response object to set the cookie on.
        token: The signed session token string.
        settings: Application settings; passed to ``cookie_attributes`` for
            ``SEARCH_SESSION_TTL``.
    """
    attrs = cookie_attributes(settings)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=attrs["max_age"],  # type: ignore[arg-type]
        path=attrs["path"],  # type: ignore[arg-type]
        httponly=attrs["httponly"],  # type: ignore[arg-type]
        secure=attrs["secure"],  # type: ignore[arg-type]
        samesite=attrs["samesite"],  # type: ignore[arg-type]
    )
