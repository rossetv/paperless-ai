"""Stream a document's PDF and thumbnail from Paperless, same-origin.

- ``GET /api/documents/{id}/pdf``   — the original PDF.
- ``GET /api/documents/{id}/thumb`` — the first-page thumbnail.

Each request builds its own :class:`~common.paperless.PaperlessClient` (it is
not thread-safe), and the streamed body owns its lifetime. Content types are
pinned or allowlisted, with ``nosniff``, so a malicious ``.html`` / ``.svg`` in
the library cannot be served as active content into the same-origin viewer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from search.deps import require_api_scope
from search.document_routes._documents import DocumentId
from search.offload import run_blocking

if TYPE_CHECKING:
    from common.config import Settings
    from common.paperless import PaperlessClient

log = structlog.get_logger(__name__)


# The upstream Content-Type is not forwarded: a malicious .html/.svg would be
# served as active content into the viewer iframe (stored XSS). The response is
# pinned to application/pdf with nosniff, inline so it renders in the viewer.
#
# The SPA frames this stream in a same-origin <iframe>, but
# SecurityHeadersMiddleware sets `X-Frame-Options: DENY` and `frame-ancestors
# 'none'` on any response that lacks them. Setting both here permits same-origin
# framing of the PDF stream only; `frame-ancestors 'self'` wins where both are
# honoured, and SAMEORIGIN covers older browsers.
_PDF_RESPONSE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Disposition": "inline",
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "frame-ancestors 'self'",
}
_PDF_MEDIA_TYPE = "application/pdf"


# The thumbnail's upstream type is forwarded only when it is one of these.
_ALLOWED_THUMB_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)
_THUMB_RESPONSE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=3600",
}


def register_proxy_routes(
    router: APIRouter,
    current_settings: Callable[[], Settings],
    *,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> None:
    """Register the PDF and thumbnail proxy routes on *router*."""
    reader_auth = Depends(require_api_scope)

    # Stops FastAPI deriving a JSON response model from the return type.
    @router.get(
        "/api/documents/{document_id}/pdf",
        dependencies=[reader_auth],
        response_class=StreamingResponse,
    )
    async def document_pdf(document_id: DocumentId) -> StreamingResponse:
        """Stream a document's original PDF from Paperless-ngx.

        404 for an unknown document; 502 when Paperless is unreachable or errors.
        """
        settings = await run_blocking(current_settings)
        return await _stream_document_pdf(document_id, settings, paperless_factory)

    @router.get(
        "/api/documents/{document_id}/thumb",
        dependencies=[reader_auth],
        response_class=StreamingResponse,
    )
    async def document_thumb(document_id: DocumentId) -> StreamingResponse:
        """Stream a document's first-page thumbnail from Paperless-ngx.

        404 for an unknown document; 502 when Paperless is unreachable, errors,
        or returns a content type outside the image allowlist.
        """
        settings = await run_blocking(current_settings)
        return await _stream_document_thumb(document_id, settings, paperless_factory)


async def _stream_document_pdf(
    document_id: int,
    settings: Settings,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> StreamingResponse:
    """Open the PDF stream, map upstream errors, and wrap the body.

    The client's connection pool is released only by ``close()``, and the body
    outlives this handler: error paths close it here, and on success
    :func:`_safe_stream` closes it when the body ends or the client disconnects.
    """
    client = paperless_factory(settings)
    try:
        _content_type, chunks = await run_blocking(
            lambda: client.download_stream(document_id)
        )
    except httpx.HTTPStatusError as exc:
        client.close()
        status = exc.response.status_code
        if status == 404:
            log.info("api.document_pdf_not_found", document_id=document_id)
            raise HTTPException(status_code=404, detail="Document not found") from exc
        # Any other upstream status is nothing the browser can act on.
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
        log.warning(
            "api.document_pdf_unreachable",
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=502, detail="Document store unavailable"
        ) from exc

    # From here the body iterator owns the client's lifetime.
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
    """Like :func:`_stream_document_pdf`, but allowlists the image content type."""
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

    # Drop parameters such as "; charset=utf-8" and forward only the base type.
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
    """Yield body chunks, then close the client however the stream ends.

    A mid-stream error cannot become an HTTP status once the response has
    begun, so it is logged and re-raised to drop the connection rather than
    truncate silently. The ``finally`` also runs on the ``GeneratorExit``
    Starlette raises when the client disconnects, so no socket leaks.
    """
    try:
        yield from chunks
    except httpx.HTTPError:
        log.warning(abort_event, document_id=document_id)
        raise
    finally:
        client.close()
