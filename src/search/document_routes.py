"""The document and search-history ``/api`` router for the search server.

This router, mounted by ``search/api.py`` alongside the search and account
routers, owns the Wave 2 backend endpoints that feed the redesigned search
UI (web-redesign §5):

- ``GET /api/documents/{id}/pdf`` — stream a document's original PDF out of
  Paperless-ngx, so the in-app DocumentPreview viewer renders it without the
  browser leaving the app.
- ``GET /api/recent-searches`` — the current user's recent searches, newest
  first, for the search UI's recent-searches strip.

The PDF proxy streams the body through the existing
:class:`~common.paperless.PaperlessClient` and maps Paperless failures to
HTTP errors: a 404 for an unknown id, a 502 for an unreachable or erroring
Paperless. A fresh ``PaperlessClient`` is built per request — the client is
**not thread-safe** (CODE_GUIDELINES §8.3) — and the blocking download is
dispatched off the event loop. The client owns an ``httpx`` connection pool;
it is closed deterministically once the streamed body is drained (or the
client disconnects), never left to garbage collection.

The proxy serves what the UI treats as a PDF: the response content type is
pinned to ``application/pdf`` with ``X-Content-Type-Options: nosniff`` rather
than forwarding Paperless's upstream type, so a malicious ``.html``/``.svg``
in the library cannot be served as active content into the same-origin
viewer iframe (CODE_GUIDELINES §10 — stored-XSS defence in depth).

Recent searches are stored per authenticated user.

Allowed deps: fastapi, starlette, httpx, structlog, appdb (recent_searches),
    search (deps, wire), common (paperless, config).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from appdb import recent_searches as recent_search_store
from common.paperless import PaperlessClient
from search.deps import get_app_db, get_current_user, require_role
from search.sessions import CurrentUser
from search.wire import RecentSearchEntry, RecentSearchesResponse

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
    """Build the ``/api`` document and search-history router (§5).

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
        return await _stream_document_pdf(document_id, settings, paperless_factory)

    @router.get("/api/recent-searches")
    def recent_searches(
        app_db: sqlite3.Connection = Depends(get_app_db),
        user: CurrentUser = Depends(get_current_user),
    ) -> RecentSearchesResponse:
        """Return the current user's recent searches, newest first.

        Auth: any authenticated user. The legacy bearer's synthetic admin
        has no user row (id=0), so it receives an empty list.
        """
        return _recent_searches(app_db, user)

    return router


# The proxy serves a document the UI treats as a PDF. The upstream
# Content-Type is deliberately NOT forwarded: a malicious .html/.svg in the
# Paperless library would otherwise be served as active content into the
# same-origin viewer iframe (a stored-XSS vector). The response is pinned to
# application/pdf, with nosniff so the browser cannot second-guess it, and an
# inline disposition so it renders in the viewer rather than downloading.
_PDF_RESPONSE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Disposition": "inline",
}
_PDF_MEDIA_TYPE = "application/pdf"


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
    paths it is closed here; on the success path :func:`_safe_chunks` closes
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
    loop = asyncio.get_event_loop()
    try:
        _content_type, chunks = await loop.run_in_executor(
            None, client.download_stream, document_id
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
        _safe_chunks(chunks, client, document_id),
        media_type=_PDF_MEDIA_TYPE,
        headers=_PDF_RESPONSE_HEADERS,
    )


def _safe_chunks(
    chunks: Iterator[bytes], client: PaperlessClient, document_id: int
) -> Iterator[bytes]:
    """Yield body chunks, logging mid-stream errors and closing the client.

    The first HTTP error inside :meth:`PaperlessClient.download_stream` is
    already mapped in :func:`_stream_document_pdf`; an error raised *while
    the body is being read* (after the response status was OK) cannot be
    turned into a clean HTTP status — the response has begun. It is logged
    and re-raised so the connection is closed rather than silently
    truncated.

    The ``finally`` closes the :class:`PaperlessClient` — releasing its
    ``httpx`` connection pool — on every exit: a fully drained body, a
    mid-stream error, or the ``GeneratorExit`` Starlette raises into this
    iterator when the client disconnects before the body is finished.
    Without it every PDF request would leak a socket (CODE_GUIDELINES §8.1).

    Args:
        chunks: The document body chunk iterator.
        client: The per-request Paperless client to close once the body is
            done streaming.
        document_id: The document id, for the log line.

    Yields:
        Each body chunk in turn.
    """
    try:
        yield from chunks
    except httpx.HTTPError:
        log.warning("api.document_pdf_stream_aborted", document_id=document_id)
        raise
    finally:
        client.close()


def _recent_searches(
    app_db: sqlite3.Connection, user: CurrentUser
) -> RecentSearchesResponse:
    """recent-searches handler body: read the user's history from app.db.

    Args:
        app_db: The per-request ``app.db`` connection.
        user: The authenticated current user.

    Returns:
        The user's recent searches as a :class:`RecentSearchesResponse`.
    """
    rows = recent_search_store.list_for_user(app_db, user.id)
    return RecentSearchesResponse(
        searches=[
            RecentSearchEntry(query=row.query, created_at=row.created_at)
            for row in rows
        ]
    )
