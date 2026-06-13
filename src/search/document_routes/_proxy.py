"""The document PDF / thumbnail streaming proxies (web-redesign §5).

Two routes stream a document's bytes out of Paperless-ngx through the search
server so the in-app viewer renders them same-origin:

- ``GET /api/documents/{id}/pdf``   — the original PDF.
- ``GET /api/documents/{id}/thumb`` — the first-page thumbnail.

Both build a fresh :class:`~common.paperless.PaperlessClient` per request — the
client is **not thread-safe** (CODE_GUIDELINES §8.3) — run the blocking
download off the event loop, and tie the client's lifetime to the streamed
body: :func:`_safe_stream` closes it in a ``finally`` once the body is drained,
on a mid-stream error, or on the ``GeneratorExit`` Starlette raises when the
client disconnects, so a request never leaks a socket (§8.1).

The PDF response content type is pinned to ``application/pdf`` (never the
upstream type) and the thumbnail type is allowlisted to known image types,
both with ``X-Content-Type-Options: nosniff`` — so a malicious ``.html`` /
``.svg`` in the Paperless library cannot be served as active content into the
same-origin viewer (§10, stored-XSS defence in depth).

Allowed deps: fastapi, starlette, httpx, structlog, common (paperless, config),
    search.deps.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from search.deps import require_api_scope
from search.offload import run_blocking

if TYPE_CHECKING:
    from common.config import Settings
    from common.paperless import PaperlessClient

log = structlog.get_logger(__name__)


# The proxy serves a document the UI treats as a PDF. The upstream
# Content-Type is deliberately NOT forwarded: a malicious .html/.svg in the
# Paperless library would otherwise be served as active content into the
# same-origin viewer iframe (a stored-XSS vector). The response is pinned to
# application/pdf, with nosniff so the browser cannot second-guess it, and an
# inline disposition so it renders in the viewer rather than downloading.
#
# Framing: the SPA embeds this stream in a same-origin <iframe>. The global
# SecurityHeadersMiddleware stamps `X-Frame-Options: DENY` and CSP
# `frame-ancestors 'none'` on every response that does not already carry them,
# which makes the browser refuse to frame the PDF ("refused to connect"). The
# middleware is additive — it skips a header a handler set itself — so this
# route overrides *both* framing controls to permit same-origin framing only:
# `X-Frame-Options: SAMEORIGIN` for older browsers, plus a CSP whose
# `frame-ancestors 'self'` takes precedence where both are present. No other
# protection is relaxed — nosniff and the pinned content-type still hold, and
# only our own PDF stream (not the app shell) becomes framable, and only by us.
_PDF_RESPONSE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Disposition": "inline",
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "frame-ancestors 'self'",
}
_PDF_MEDIA_TYPE = "application/pdf"


# The thumbnail proxy forwards the image content-type from Paperless, but only
# if it is a known image type. This prevents a malicious .html/.svg stored in
# Paperless from being served as active content through the thumbnail endpoint.
_ALLOWED_THUMB_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)
_THUMB_RESPONSE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=3600",
}


def register_proxy_routes(
    router: APIRouter,
    settings: Settings,
    *,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> None:
    """Register the PDF and thumbnail proxy routes on *router*.

    Args:
        router: The shared document router to add the routes to.
        settings: Application settings, forwarded to the Paperless client
            factory.
        paperless_factory: Builds the per-request :class:`PaperlessClient`.
    """
    reader_auth = Depends(require_api_scope)

    # response_class=StreamingResponse: the handler returns a hand-built
    # streaming response, so FastAPI must not derive a JSON response model.
    @router.get(
        "/api/documents/{document_id}/pdf",
        dependencies=[reader_auth],
        response_class=StreamingResponse,
    )
    async def document_pdf(document_id: int) -> StreamingResponse:
        """Stream a document's original PDF from Paperless-ngx.

        Auth: Read-only or above, plus the ``api`` scope for an API-key
        caller. A 404 is returned for an unknown document id; a 502 when
        Paperless is unreachable or returns a server error.
        """
        return await _stream_document_pdf(document_id, settings, paperless_factory)

    @router.get(
        "/api/documents/{document_id}/thumb",
        dependencies=[reader_auth],
        response_class=StreamingResponse,
    )
    async def document_thumb(document_id: int) -> StreamingResponse:
        """Stream a document's first-page thumbnail from Paperless-ngx.

        Auth: Read-only or above, plus the ``api`` scope for an API-key
        caller. A 404 is returned for an unknown document id; a 502 when
        Paperless is unreachable or returns a server error.

        The response content type is forwarded from Paperless (usually
        ``image/jpeg`` or ``image/webp``), but only image/* types are
        permitted — anything else is rejected as 502 to prevent a malicious
        document from serving active content through this endpoint.
        """
        return await _stream_document_thumb(document_id, settings, paperless_factory)


async def _stream_document_pdf(
    document_id: int,
    settings: Settings,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> StreamingResponse:
    """PDF-proxy handler body: open the stream, map errors, wrap the body.

    The blocking ``download_stream`` (it opens an HTTP connection) is run on
    the event loop's default executor so the loop stays free. The returned
    :class:`StreamingResponse` then drains the chunk iterator as it writes.

    The per-request :class:`PaperlessClient` owns an ``httpx`` connection
    pool that only an explicit ``close()`` releases. The body iterator
    outlives this handler, so the close is tied to the stream: on the error
    paths it is closed here; on the success path :func:`_safe_stream` closes
    it in a ``finally`` once the body is drained — or once Starlette cancels
    the iterator on a client disconnect.

    Args:
        document_id: The Paperless-ngx document id.
        settings: Application settings.
        paperless_factory: Builds the per-request Paperless client.

    Returns:
        A :class:`StreamingResponse` over the document body, pinned to the
        ``application/pdf`` content type with ``nosniff``.

    Raises:
        HTTPException: ``404`` for an unknown document; ``502`` when
            Paperless is unreachable or returns a server error.
    """
    client = paperless_factory(settings)
    try:
        _content_type, chunks = await run_blocking(
            lambda: client.download_stream(document_id)
        )
    except httpx.HTTPStatusError as exc:
        # download_stream failed before returning a body; nothing will drain
        # the chunk iterator, so close the client here.
        client.close()
        status = exc.response.status_code
        if status == 404:
            log.info("api.document_pdf_not_found", document_id=document_id)
            raise HTTPException(status_code=404, detail="Document not found") from exc
        # Any other Paperless HTTP error — a 5xx, a 403 — is an upstream
        # failure the browser cannot act on: report a 502.
        log.warning(
            "api.document_pdf_upstream_error",
            document_id=document_id,
            upstream_status=status,
        )
        raise HTTPException(
            status_code=502, detail="Document store unavailable"
        ) from exc
    except httpx.HTTPError as exc:
        client.close()
        # A network-level failure (connect error, timeout, read error).
        log.warning(
            "api.document_pdf_unreachable",
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=502, detail="Document store unavailable"
        ) from exc

    # Success: the body iterator now owns the client's lifetime — it closes
    # the client when fully drained, on a mid-stream error, or on the
    # GeneratorExit Starlette raises when the client disconnects early.
    return StreamingResponse(
        _safe_stream(
            chunks,
            client,
            document_id=document_id,
            abort_event="api.document_pdf_stream_aborted",
        ),
        media_type=_PDF_MEDIA_TYPE,
        headers=_PDF_RESPONSE_HEADERS,
    )


async def _stream_document_thumb(
    document_id: int,
    settings: Settings,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> StreamingResponse:
    """Thumbnail-proxy handler body: open the stream, map errors, wrap the body.

    Mirrors :func:`_stream_document_pdf` but uses
    :meth:`~common.paperless.PaperlessClient.thumb_stream` and validates that
    the upstream content type is an image — not active content — before
    forwarding it. Any non-image type is treated as a 502 upstream error.

    Args:
        document_id: The Paperless-ngx document id.
        settings: Application settings.
        paperless_factory: Builds the per-request Paperless client.

    Returns:
        A :class:`StreamingResponse` over the thumbnail body, with
        ``Cache-Control: private, max-age=3600`` and ``nosniff``.

    Raises:
        HTTPException: ``404`` for an unknown document; ``502`` when
            Paperless is unreachable, returns a server error, or delivers
            a non-image content type.
    """
    client = paperless_factory(settings)
    try:
        content_type, chunks = await run_blocking(
            lambda: client.thumb_stream(document_id)
        )
    except httpx.HTTPStatusError as exc:
        client.close()
        status = exc.response.status_code
        if status == 404:
            log.info("api.document_thumb_not_found", document_id=document_id)
            raise HTTPException(status_code=404, detail="Document not found") from exc
        log.warning(
            "api.document_thumb_upstream_error",
            document_id=document_id,
            upstream_status=status,
        )
        raise HTTPException(
            status_code=502, detail="Document store unavailable"
        ) from exc
    except httpx.HTTPError as exc:
        client.close()
        log.warning(
            "api.document_thumb_unreachable",
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=502, detail="Document store unavailable"
        ) from exc

    # Normalise content-type: strip parameters (e.g. "; charset=utf-8") before
    # the allowlist check, but forward only the base type.
    base_content_type = content_type.split(";")[0].strip().lower()
    if base_content_type not in _ALLOWED_THUMB_CONTENT_TYPES:
        client.close()
        log.warning(
            "api.document_thumb_unexpected_content_type",
            document_id=document_id,
            content_type=content_type,
        )
        raise HTTPException(status_code=502, detail="Document store unavailable")

    return StreamingResponse(
        _safe_stream(
            chunks,
            client,
            document_id=document_id,
            abort_event="api.document_thumb_stream_aborted",
        ),
        media_type=base_content_type,
        headers=_THUMB_RESPONSE_HEADERS,
    )


def _safe_stream(
    chunks: Iterator[bytes],
    client: PaperlessClient,
    *,
    document_id: int,
    abort_event: str,
) -> Iterator[bytes]:
    """Yield body chunks, logging a mid-stream error and closing the client.

    The single streaming generator shared by the PDF and thumbnail proxies
    (CODE_GUIDELINES §1.9): the only difference between the two was the log
    event string, now a parameter (*abort_event*).

    The first HTTP error inside the download is already mapped in the calling
    handler; an error raised *while the body is being read* (after the response
    status was OK) cannot be turned into a clean HTTP status — the response has
    begun. It is logged and re-raised so the connection is closed rather than
    silently truncated.

    The ``finally`` closes the :class:`PaperlessClient` — releasing its
    ``httpx`` connection pool — on every exit: a fully drained body, a
    mid-stream error, or the ``GeneratorExit`` Starlette raises into this
    iterator when the client disconnects before the body is finished. Without
    it every proxied request would leak a socket (CODE_GUIDELINES §8.1).

    Args:
        chunks: The document/thumbnail body chunk iterator.
        client: The per-request Paperless client to close once the body is
            done streaming.
        document_id: The document id, for the log line.
        abort_event: The structured-log event name for a mid-stream abort.

    Yields:
        Each body chunk in turn.
    """
    try:
        yield from chunks
    except httpx.HTTPError:
        log.warning(abort_event, document_id=document_id)
        raise
    finally:
        client.close()
