"""Global response-header middleware for the search server (defence in depth).

A single ASGI middleware that stamps a conservative, SPA-safe security-header
set onto every response — the API routers, the MCP mount, and the static React
SPA alike. The headers are a belt-and-braces layer: the real authentication and
authorisation live in the routers; these headers shrink the blast radius of a
mistake elsewhere (clickjacking, MIME sniffing, referrer leakage, a stray
injected ``<script>``).

The Content-Security-Policy is deliberately *permissive-but-present*: it is
crafted against the actual built ``web/dist/index.html`` so it never blanks the
app, while still locking out the things the SPA never needs (cross-origin
framing, plugins, a different ``<base>``).

CSP rationale — checked against the built SPA:
- ``default-src 'self'`` — same-origin by default; the app fetches only its own
  ``/api`` and ``/assets`` paths.
- ``script-src 'self' 'unsafe-inline'`` — the hashed bundle is same-origin, and
  ``index.html`` carries ONE inline ``<script>`` (the pre-paint theme bootstrap)
  with no nonce. A static mount cannot stamp a per-request nonce, so
  ``'unsafe-inline'`` admits that one script. There is no ``eval`` / ``new
  Function`` in the bundle, so ``'unsafe-eval'`` is deliberately withheld.
- ``style-src 'self' 'unsafe-inline'`` — the Vite/React runtime injects
  ``<style>`` elements at runtime, so inline styles must be allowed or the app
  renders unstyled.
- ``img-src 'self' data:`` — same-origin images plus ``data:`` URIs for any
  runtime-generated/inlined icons.
- ``font-src 'self'`` — the FontAwesome ``woff2`` files are served from
  ``/assets`` (same origin); no external font CDN is used.
- ``connect-src 'self'`` — ``fetch`` / NDJSON streams target same-origin
  ``/api`` only.
- ``frame-ancestors 'none'`` — the app is never framed (mirrors the
  ``X-Frame-Options: DENY`` header for older browsers).
- ``base-uri 'self'`` and ``object-src 'none'`` — block ``<base>`` hijacking and
  legacy plugin embedding; the SPA uses neither.

Allowed deps: starlette. Forbidden: fastapi, sqlite3, store, the search
    pipeline.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The Content-Security-Policy, assembled once at import time. Permissive enough
# to serve the built SPA unchanged (see the module docstring for the per-
# directive justification) yet still an enforcing policy, not Report-Only.
_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "object-src 'none'",
    )
)

# The conservative, SPA-safe header set applied to every response. HSTS is set
# unconditionally: the documented deployment is HTTPS behind nginx/Cloudflare,
# and a browser ignores the header on a plain-HTTP response, so there is no harm
# in sending it on the rare direct-HTTP hit during local development.
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"content-security-policy", _CONTENT_SECURITY_POLICY.encode("ascii")),
)


class SecurityHeadersMiddleware:
    """ASGI middleware that adds the security headers to every HTTP response.

    Wraps the ``http.response.start`` message to append the header set before it
    is sent. Non-HTTP scopes (lifespan, websocket) pass straight through. An
    existing header of the same name is left in place — a handler that
    deliberately set its own (none does today) is not overridden, which keeps
    the middleware purely additive.

    Args:
        app: The inner ASGI application to wrap.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {name.lower() for name, _ in headers}
                for name, value in _SECURITY_HEADERS:
                    if name not in present:
                        headers.append((name, value))
            await send(message)

        await self._app(scope, receive, send_with_headers)
