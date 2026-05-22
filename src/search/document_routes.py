"""The document and search-history ``/api`` router for the search server.

This router, mounted by ``search/api.py`` alongside the search and account
routers, owns the Wave 2 backend endpoints that feed the redesigned search
UI (web-redesign §5):

- ``GET /api/documents/{id}/pdf`` — stream a document's original PDF out of
  Paperless-ngx, so the in-app DocumentPreview viewer renders it without the
  browser leaving the app. (Recent-searches route added in W2B6.)

The PDF proxy streams the body through the existing
:class:`~common.paperless.PaperlessClient` — buffering a large scan into
memory per request is wasteful — and maps Paperless failures to HTTP errors:
a 404 for an unknown id, a 502 for an unreachable or erroring Paperless.

A fresh ``PaperlessClient`` is built per request: the client is **not
thread-safe** (CODE_GUIDELINES §8.3) and this router runs on FastAPI's
thread pool. The blocking download is dispatched off the event loop.

Allowed deps: fastapi, starlette, httpx, structlog, search (deps),
    common (paperless, config).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from common.paperless import PaperlessClient
from search.deps import require_role

if TYPE_CHECKING:
    from common.config import Settings

log = structlog.get_logger(__name__)


def _default_paperless_factory(settings: Settings) -> PaperlessClient:
    """Build a real :class:`PaperlessClient` from *settings*.

    The production factory. Tests pass their own factory returning a stub so
    the router never makes a real Paperless call.
    """
    return PaperlessClient(settings)


def build_document_router(
    settings: Settings,
    *,
    paperless_factory: Callable[[Settings], PaperlessClient] = (
        _default_paperless_factory
    ),
) -> APIRouter:
    """Build the ``/api`` document router (web-redesign §5).

    Args:
        settings: Application settings, forwarded to the Paperless client
            factory.
        paperless_factory: Builds the :class:`PaperlessClient` for a request.
            Defaults to the real client; tests inject a stub factory.

    Returns:
        A configured :class:`~fastapi.APIRouter`.
    """
    router = APIRouter()
    reader_auth = Depends(require_role("readonly"))

    # response_class=StreamingResponse: the handler returns a hand-built
    # streaming response, so FastAPI must not derive a JSON response model.
    @router.get(
        "/api/documents/{document_id}/pdf",
        dependencies=[reader_auth],
        response_class=StreamingResponse,
    )
    async def document_pdf(document_id: int) -> StreamingResponse:
        """Stream a document's original PDF from Paperless-ngx.

        Auth: any authenticated user (Read-only or above). A 404 is returned
        for an unknown document id; a 502 when Paperless is unreachable or
        returns a server error.
        """
        return await _stream_document_pdf(
            document_id, settings, paperless_factory
        )

    return router


async def _stream_document_pdf(
    document_id: int,
    settings: Settings,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> StreamingResponse:
    """PDF-proxy handler body: open the stream, map errors, wrap the body.

    The blocking ``download_stream`` (it opens an HTTP connection) is run on
    the event loop's default executor so the loop stays free. The returned
    :class:`StreamingResponse` then drains the chunk iterator as it writes.

    Args:
        document_id: The Paperless-ngx document id.
        settings: Application settings.
        paperless_factory: Builds the per-request Paperless client.

    Returns:
        A :class:`StreamingResponse` over the document body.

    Raises:
        HTTPException: ``404`` for an unknown document; ``502`` when
            Paperless is unreachable or returns a server error.
    """
    client = paperless_factory(settings)
    loop = asyncio.get_event_loop()
    try:
        content_type, chunks = await loop.run_in_executor(
            None, client.download_stream, document_id
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            log.info("api.document_pdf_not_found", document_id=document_id)
            raise HTTPException(
                status_code=404, detail="Document not found"
            ) from exc
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
        # A network-level failure (connect error, timeout, read error).
        log.warning(
            "api.document_pdf_unreachable",
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=502, detail="Document store unavailable"
        ) from exc

    return StreamingResponse(
        _safe_chunks(chunks, document_id),
        media_type=content_type,
    )


def _safe_chunks(
    chunks: Iterator[bytes], document_id: int
) -> Iterator[bytes]:
    """Yield body chunks, logging any error raised mid-stream.

    The first HTTP error inside :meth:`PaperlessClient.download_stream` is
    already mapped in :func:`_stream_document_pdf`; an error raised *while
    the body is being read* (after the response status was OK) cannot be
    turned into a clean HTTP status — the response has begun. It is logged
    and re-raised so the connection is closed rather than silently
    truncated.

    Args:
        chunks: The document body chunk iterator.
        document_id: The document id, for the log line.

    Yields:
        Each body chunk in turn.
    """
    try:
        yield from chunks
    except httpx.HTTPError:
        log.warning("api.document_pdf_stream_aborted", document_id=document_id)
        raise
