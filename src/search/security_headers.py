"""ASGI middleware that adds security headers to every response.

Defence in depth for the API, the MCP mount, and the SPA alike. The CSP is
written against the built ``web/dist/index.html`` so it never blanks the app:

- ``default-src 'self'`` — same-origin by default; the app fetches only its own
  ``/api`` and ``/assets`` paths.
- ``script-src 'self' 'unsafe-inline'`` — the hashed bundle is same-origin, and
  ``index.html`` carries one inline ``<script>`` (the pre-paint theme bootstrap)
  and a static mount cannot stamp a per-request nonce. The bundle has no
  ``eval``, so ``'unsafe-eval'`` is withheld.
- ``style-src 'self' 'unsafe-inline'`` — the runtime injects ``<style>``
  elements, so the app renders unstyled without it.
- ``img-src 'self' data:`` — same-origin images plus ``data:`` URIs for any
  runtime-generated/inlined icons.
- ``font-src 'self'`` — the FontAwesome ``woff2`` files are served from
  ``/assets`` (same origin); no external font CDN is used.
- ``connect-src 'self'`` — ``fetch`` / NDJSON streams target same-origin
  ``/api`` only.
- ``frame-ancestors 'none'`` — the app is never framed (``X-Frame-Options:
  DENY`` covers older browsers).
- ``base-uri 'self'`` and ``object-src 'none'`` — block ``<base>`` hijacking and
  plugin embedding; the SPA uses neither.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Enforcing, not Report-Only.
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

# HSTS is sent unconditionally: deployment is HTTPS behind a proxy, and browsers
# ignore it on a plain-HTTP response such as a local development hit.
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"content-security-policy", _CONTENT_SECURITY_POLICY.encode("ascii")),
)


class SecurityHeadersMiddleware:
    """ASGI middleware that adds the security headers to every HTTP response.

    A header the handler already set is left alone; the PDF proxy relies on
    this to permit same-origin framing.
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
