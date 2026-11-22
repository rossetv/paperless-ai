"""ASGI middleware that refuses oversized request bodies before anything reads them.

It sits inside :class:`~search.security_headers.SecurityHeadersMiddleware` so the
413 carries the same headers as every other response, and outside routing so it
runs before authentication and body parsing. The largest legitimate body is a
settings update, which stays under the limit.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# A settings update is bounded in characters (100 values of 8192), which JSON-escaped
# non-ASCII text can stretch to about 5 MiB of bytes.
MAX_BODY_BYTES = 8 * 1024 * 1024


def _too_large() -> JSONResponse:
    # Built per refusal: middleware further out appends to a response's raw headers in place.
    return JSONResponse(status_code=413, content={"detail": "Request body too large"})


class BodyLimitMiddleware:
    """Answer 413 to a request whose body exceeds *max_bytes*.

    A declared ``Content-Length`` over the limit is refused without calling the
    app. A body with no (or a false) length is counted as it streams, and
    reading stops once it passes the limit.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break  # the server rejects a malformed length itself
                if declared > self._max_bytes:
                    await _too_large()(scope, receive, send)
                    return
                break

        received = 0
        refused = False
        response_started = False
        answered = False

        async def counting_receive() -> Message:
            nonlocal received, refused, answered
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    refused = True
                    if not response_started:
                        answered = True
                        await _too_large()(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            # Once the 413 is out, whatever the app answers to the cut-off body is dropped.
            if not answered:
                await send(message)

        await self._app(scope, counting_receive, guarded_send)
