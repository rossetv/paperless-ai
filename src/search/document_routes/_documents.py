"""The single-document ``/api`` routes and the recent-searches read.

The document-centric endpoints feeding the search UI (web-redesign §5):

- ``GET    /api/documents/{id}``              — the wire summary for one document.
- ``PATCH  /api/documents/{id}``              — update editable metadata.
- ``DELETE /api/documents/{id}``              — delete the document (admin only).
- ``POST   /api/documents/{id}/reclassify``   — re-queue for classification.
- ``POST   /api/documents/{id}/retranscribe`` — re-queue for OCR.
- ``GET    /api/recent-searches``             — the caller's recent searches.

The summary read goes through the injected :class:`~store.reader.StoreReader`;
the mutations proxy to the per-request :class:`~common.paperless.PaperlessClient`
(built fresh — it is not thread-safe, §8.3 — and closed in a ``finally``); the
re-queue endpoints swap a Paperless tag so the relevant daemon picks the
document up on its next poll. Recent searches are read from ``app.db`` per user.

Allowed deps: fastapi, starlette, sqlite3, structlog, appdb (recent_searches),
    common (paperless, paperless_types, config), search (deps, sessions, wire).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import Response

from appdb import recent_searches as recent_search_store
from common.paperless_types import DocumentMetadataUpdate
from search.offload import run_blocking
from search.deps import (
    get_app_db,
    require_admin,
    require_api_scope,
    require_api_scope_member,
)
from search.sessions import CurrentUser
from search.wire import (
    DocumentPatchRequest,
    DocumentSummaryResponse,
    RecentSearchEntry,
    RecentSearchesResponse,
    to_document_summary_response,
)

if TYPE_CHECKING:
    from common.config import Settings
    from common.paperless import PaperlessClient
    from store.reader import StoreReader

log = structlog.get_logger(__name__)


def register_document_routes(
    router: APIRouter,
    settings: Settings,
    *,
    store_reader: StoreReader,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> None:
    """Register the single-document and recent-searches routes on *router*.

    Args:
        router: The shared document router to add the routes to.
        settings: Application settings, forwarded to the Paperless client
            factory and used to build the Paperless deep-link URL.
        store_reader: The store reader used by the document-summary route.
        paperless_factory: Builds the per-request :class:`PaperlessClient`.
    """

    @router.get(
        "/api/documents/{document_id}",
        dependencies=[Depends(require_api_scope)],
        response_model=DocumentSummaryResponse,
    )
    async def document_summary(document_id: int) -> DocumentSummaryResponse:
        """Return the summary for a single document by id.

        Used by the shareable SPA routes (``/documents/{id}``) to fetch the
        document metadata needed to render the DocumentPreviewScreen without a
        full library list.

        Auth: Read-only or above, plus the ``api`` scope for an API-key
        caller. A 404 is returned when *document_id* is not present in the
        store.
        """
        summary = await run_blocking(
            lambda: store_reader.get_document_summary(document_id)
        )
        if summary is None:
            raise HTTPException(status_code=404, detail="document not found")
        paperless_url = f"{settings.PAPERLESS_URL.rstrip('/')}/documents/{document_id}/"
        return to_document_summary_response(summary, paperless_url=paperless_url)

    @router.get("/api/recent-searches")
    def recent_searches(
        app_db: sqlite3.Connection = Depends(get_app_db),
        user: CurrentUser = Depends(require_api_scope),
    ) -> RecentSearchesResponse:
        """Return the current user's recent searches, newest first.

        Auth: Read-only or above, plus the ``api`` scope for an API-key
        caller.
        """
        return _recent_searches(app_db, user)

    @router.patch(
        "/api/documents/{document_id}",
        dependencies=[Depends(require_api_scope_member)],
    )
    async def patch_document(
        document_id: int,
        body: DocumentPatchRequest,
    ) -> DocumentSummaryResponse:
        """Update editable document metadata.

        Proxies to :meth:`~common.paperless.PaperlessClient.update_document_metadata`.
        Returns the re-read summary from the search index. Note: the store index
        only reflects the edit after the next reconcile cycle, so the response
        may carry pre-edit values; the frontend uses optimistic UI to hide this
        asymmetry from the user.

        Auth: Member-or-above; read-only callers receive a 403. A 404 is
        returned when *document_id* is not present in the store after the
        Paperless update.
        """
        return await _patch_document(
            document_id, body, settings, store_reader, paperless_factory
        )

    @router.post(
        "/api/documents/{document_id}/reclassify",
        status_code=202,
        dependencies=[Depends(require_api_scope_member)],
    )
    async def reclassify_document(document_id: int) -> Response:
        """Re-queue this document for classification.

        Removes the classify-post tag (if present) and adds the classify-pre
        tag, so the classifier daemon picks the document up on its next poll.
        The daemon swaps the tags back on completion.

        Auth: Member or above.
        """
        await _swap_pipeline_tag(
            document_id,
            settings,
            paperless_factory,
            remove_tag=settings.CLASSIFY_POST_TAG_ID,
            add_tag=settings.CLASSIFY_PRE_TAG_ID,
        )
        return Response(status_code=202)

    @router.post(
        "/api/documents/{document_id}/retranscribe",
        status_code=202,
        dependencies=[Depends(require_api_scope_member)],
    )
    async def retranscribe_document(document_id: int) -> Response:
        """Re-queue this document for OCR retranscription.

        Removes the OCR-post tag (if present) and adds the OCR-pre tag, so
        the OCR daemon picks the document up on its next poll. Because the
        OCR daemon typically also triggers classification, this effectively
        re-runs the full pipeline for the document.

        Auth: Member or above.
        """
        await _swap_pipeline_tag(
            document_id,
            settings,
            paperless_factory,
            remove_tag=settings.POST_TAG_ID,
            add_tag=settings.PRE_TAG_ID,
        )
        return Response(status_code=202)

    @router.delete(
        "/api/documents/{document_id}",
        status_code=204,
        dependencies=[Depends(require_admin)],
    )
    async def delete_document(document_id: int) -> Response:
        """Delete the document from Paperless-ngx.

        Proxies to :meth:`~common.paperless.PaperlessClient.delete_document`.
        The document is removed from Paperless and will be purged from the
        search index on the next reconcile cycle.

        Auth: Admin only.
        """
        paperless = paperless_factory(settings)
        try:
            await run_blocking(lambda: paperless.delete_document(document_id))
        finally:
            paperless.close()
        return Response(status_code=204)


async def _patch_document(
    document_id: int,
    body: DocumentPatchRequest,
    settings: Settings,
    store_reader: StoreReader,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> DocumentSummaryResponse:
    """PATCH handler body: forward the set fields, then re-read the summary.

    Args:
        document_id: The Paperless-ngx document id.
        body: The validated patch request.
        settings: Application settings.
        store_reader: The store reader for the post-update summary.
        paperless_factory: Builds the per-request Paperless client.

    Returns:
        The re-read :class:`DocumentSummaryResponse`.

    Raises:
        HTTPException: ``404`` when the document is absent from the store after
            the Paperless update.
    """
    # Build kwargs from the *set* fields only — Pydantic tracks which fields
    # were explicitly supplied via model_fields_set, so we can distinguish
    # "field absent (do not touch)" from "field explicit null (clear it)".
    # Built into a DocumentMetadataUpdate TypedDict so mypy can narrow the
    # **kwargs splat to the expected per-field types.
    fields_set = body.model_fields_set
    kwargs: DocumentMetadataUpdate = {}
    if "title" in fields_set:
        kwargs["title"] = body.title
    if "correspondent_id" in fields_set:
        kwargs["correspondent_id"] = body.correspondent_id
    if "document_type_id" in fields_set:
        kwargs["document_type_id"] = body.document_type_id
    if "document_date" in fields_set:
        kwargs["document_date"] = body.document_date
    # tags=None is meaningless (no opinion on tags); only forward a concrete list.
    if "tags" in fields_set and body.tags is not None:
        kwargs["tags"] = set(body.tags)
    if "notes" in fields_set:
        kwargs["notes"] = body.notes
    if "archive_serial_number" in fields_set:
        kwargs["archive_serial_number"] = body.archive_serial_number

    paperless = paperless_factory(settings)
    try:
        await run_blocking(
            lambda: paperless.update_document_metadata(document_id, **kwargs)
        )
    finally:
        paperless.close()

    summary = await run_blocking(lambda: store_reader.get_document_summary(document_id))
    if summary is None:
        raise HTTPException(status_code=404, detail="document not found")
    return to_document_summary_response(
        summary,
        paperless_url=f"{settings.PAPERLESS_URL.rstrip('/')}/documents/{document_id}/",
    )


async def _swap_pipeline_tag(
    document_id: int,
    settings: Settings,
    paperless_factory: Callable[[Settings], PaperlessClient],
    *,
    remove_tag: int | None,
    add_tag: int,
) -> None:
    """Read the document's tags, remove one tag, add another, write back.

    The remove step is skipped when *remove_tag* is ``None`` (the setting
    is not configured) or the tag is not present on the document. This
    lets the reclassify and retranscribe endpoints behave correctly even
    when the post-processing tag is absent or unconfigured.

    Args:
        document_id: The Paperless-ngx document id.
        settings: Application settings.
        paperless_factory: Builds the per-request Paperless client.
        remove_tag: The tag id to remove, or ``None`` to skip removal.
        add_tag: The tag id to add.
    """
    paperless = paperless_factory(settings)
    try:
        doc = await run_blocking(lambda: paperless.get_document(document_id))
        current: set[int] = set(doc.get("tags") or [])
        if remove_tag is not None:
            current.discard(remove_tag)
        current.add(add_tag)
        await run_blocking(
            lambda: paperless.update_document_metadata(document_id, tags=current)
        )
    finally:
        paperless.close()


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
