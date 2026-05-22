"""Session-cookie set and clear for the search server.

Two thin helpers over a Starlette/FastAPI ``Response``:
:func:`set_session_cookie` writes the opaque session token with every
required security flag, and :func:`clear_session_cookie` removes it on
logout. The cookie's name and security attributes live here so they have
exactly one home.

The cookie is ``HttpOnly`` (a JavaScript XSS bug cannot read the token),
``SameSite=Strict`` (never sent cross-site — the CSRF defence, spec §4.4),
and scoped to ``Path=/``. The ``Secure`` flag is conditional on the request
scheme: set it over HTTPS, omit it over HTTP — a ``Secure`` cookie is
silently dropped by the browser over HTTP, which makes login appear to
succeed (200) but leaves no session cookie. The caller derives the flag as
``secure = request.url.scheme == "https"``. ``Max-Age`` is supplied by the
caller: seven days for a "remember me" login, eight hours otherwise.

Deployment note: run uvicorn with ``--proxy-headers`` so that
``request.url.scheme`` reflects the real edge scheme (HTTPS) behind
nginx/Cloudflare, not the plain-HTTP hop from the reverse proxy to the
origin.

Depends on: starlette/fastapi Response, search.auth (the cookie name).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from search.auth import SESSION_COOKIE_NAME

if TYPE_CHECKING:
    from starlette.responses import Response


def set_session_cookie(
    response: Response, *, token: str, max_age: int, secure: bool
) -> None:
    """Write the opaque session *token* onto *response* with all security flags.

    Args:
        response: The response to set the cookie on.
        token: The raw opaque session token (from
            :func:`search.sessions.begin_session`).
        max_age: The cookie lifetime in seconds; the browser drops the cookie
            after this, in step with the server-side session expiry.
        secure: Whether to set the ``Secure`` cookie flag. Pass
            ``request.url.scheme == "https"`` so the flag is present over
            HTTPS and absent over plain HTTP — a ``Secure`` cookie is silently
            dropped over HTTP.
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
    """Delete the session cookie from *response* (the logout path).

    Uses the same name and ``Path`` as :func:`set_session_cookie` so the
    browser actually drops the right cookie.

    Args:
        response: The response to clear the cookie on.
    """
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
