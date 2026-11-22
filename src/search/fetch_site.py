"""ASGI middleware that refuses cookie-authenticated changes sent from another site.

A browser marks each request with ``Sec-Fetch-Site``. A state-changing request
that carries the session cookie and is marked ``same-site`` or ``cross-site``
did not come from the app's own pages, so it is answered 403 before routing.
``same-origin``, ``none`` (typed or bookmarked) and an absent header (older
browsers, non-browser clients) pass, as does a request carrying an API key and
no session cookie: a page on another origin cannot attach a key without a CORS
grant the app never gives. The cookie decides, whatever Authorization holds,
because the session cookie is tried before the key. Host and Origin are not
compared, so a reverse proxy changes nothing.
"""

from __future__ import annotations

from starlette.requests import cookie_parser
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from search.auth import SESSION_COOKIE_NAME

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_OTHER_SITE = frozenset({"same-site", "cross-site"})


def _forbidden() -> JSONResponse:
    # Built per refusal: middleware further out appends to a response's raw headers in place.
    return JSONResponse(
        status_code=403,
        content={"detail": "You do not have permission to perform this action"},
    )


class FetchSiteMiddleware:
    """Answer 403 to an unsafe cookie-session request marked as from another site."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _UNSAFE_METHODS:
            await self._app(scope, receive, send)
            return

        fetch_site = ""
        cookies: list[str] = []
        for name, value in scope["headers"]:
            if name == b"sec-fetch-site":
                fetch_site = value.decode("latin-1").strip().lower()
            elif name == b"cookie":
                cookies.append(value.decode("latin-1"))

        if fetch_site in _OTHER_SITE and SESSION_COOKIE_NAME in cookie_parser(
            "; ".join(cookies)
        ):
            await _forbidden()(scope, receive, send)
            return
        await self._app(scope, receive, send)
