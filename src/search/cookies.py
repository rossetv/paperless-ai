"""Set and clear the session cookie.

The cookie is ``HttpOnly`` (XSS cannot read it) and ``SameSite=Strict`` (the
CSRF defence). ``Secure`` follows the request scheme, because browsers silently
drop a ``Secure`` cookie over HTTP and login would appear to succeed with no
session. Behind a proxy, uvicorn needs ``--proxy-headers`` for the scheme to be
the edge's HTTPS.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from search.auth import SESSION_COOKIE_NAME

if TYPE_CHECKING:
    from starlette.responses import Response


def set_session_cookie(
    response: Response, *, token: str, max_age: int, secure: bool
) -> None:
    """Write the session *token* onto *response* with the security flags.

    Pass ``secure=request.url.scheme == "https"``.
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path="/",
        httponly=True,
        secure=secure,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    """Delete the session cookie; name and ``Path`` must match the set call."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
