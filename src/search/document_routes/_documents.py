"""The single-document ``/api`` routes and the recent-searches read.

- ``GET    /api/documents/{id}``              — the wire summary for one document.
- ``PATCH  /api/documents/{id}``              — update editable metadata.
- ``DELETE /api/documents/{id}``              — delete the document (admin only).
- ``POST   /api/documents/{id}/reclassify``   — re-queue for classification.
- ``POST   /api/documents/{id}/retranscribe`` — re-queue for OCR.
- ``GET    /api/recent-searches``             — the caller's recent searches.

Mutations go to Paperless through a :class:`~common.paperless.PaperlessClient`
built per request, because it is not thread-safe. The re-queue endpoints swap a
pipeline tag so the relevant daemon picks the document up on its next poll.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path
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

# The index stores ids as SQLite INTEGER; a larger one can name no document.
DocumentId = Annotated[int, Path(le=2**63 - 1)]


def register_document_routes(
    router: APIRouter,
    current_settings: Callable[[], Settings],
    *,
    store_reader: StoreReader,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> None:
    """Register the single-document and recent-searches routes on *router*."""

    @router.get(
        "/api/documents/{document_id}",
        dependencies=[Depends(require_api_scope)],
        response_model=DocumentSummaryResponse,
    )
    async def document_summary(document_id: DocumentId) -> DocumentSummaryResponse:
        """Return the summary for one document; 404 when it is not indexed.

        Backs the shareable ``/documents/{id}`` SPA route.
        """
        summary = await run_blocking(
            lambda: store_reader.get_document_summary(document_id)
        )
        if summary is None:
            raise HTTPException(status_code=404, detail="document not found")
        settings = await run_blocking(current_settings)
        paperless_url = (
            f"{settings.PAPERLESS_PUBLIC_URL.rstrip('/')}/documents/{document_id}/"
        )
        return to_document_summary_response(summary, paperless_url=paperless_url)

    @router.get("/api/recent-searches")
    def recent_searches(
        app_db: sqlite3.Connection = Depends(get_app_db),
        user: CurrentUser = Depends(require_api_scope),
    ) -> RecentSearchesResponse:
        """Return the current user's recent searches, newest first."""
        return _recent_searches(app_db, user)

    @router.patch(
        "/api/documents/{document_id}",
        dependencies=[Depends(require_api_scope_member)],
    )
    async def patch_document(
        document_id: DocumentId,
        body: DocumentPatchRequest,
    ) -> DocumentSummaryResponse:
        """Update editable document metadata in Paperless (Member or above).

        The returned summary is re-read from the search index, which only sees
        the edit after the next reconcile, so it may carry pre-edit values; the
        frontend hides this with an optimistic update.
        """
        return await _patch_document(
            document_id,
            body,
            await run_blocking(current_settings),
            store_reader,
            paperless_factory,
        )

    @router.post(
        "/api/documents/{document_id}/reclassify",
        status_code=202,
        dependencies=[Depends(require_api_scope_member)],
    )
    async def reclassify_document(document_id: DocumentId) -> Response:
        """Re-queue this document for classification (Member or above)."""
        settings = await run_blocking(current_settings)
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
    async def retranscribe_document(document_id: DocumentId) -> Response:
        """Re-queue this document for OCR (Member or above).

        OCR usually triggers classification too, so this re-runs the full
        pipeline.
        """
        settings = await run_blocking(current_settings)
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
    async def delete_document(document_id: DocumentId) -> Response:
        """Delete the document from Paperless (admin only).

        The search index drops it on the next reconcile.
        """
        paperless = paperless_factory(await run_blocking(current_settings))
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
    """Forward the fields the client sent, then re-read the summary."""
    # model_fields_set separates an absent field (leave it) from an explicit
    # null (clear it).
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
        paperless_url=f"{settings.PAPERLESS_PUBLIC_URL.rstrip('/')}/documents/{document_id}/",
    )


async def _swap_pipeline_tag(
    document_id: int,
    settings: Settings,
    paperless_factory: Callable[[Settings], PaperlessClient],
    *,
    remove_tag: int | None,
    add_tag: int,
) -> None:
    """Remove *remove_tag* (when set) and add *add_tag* on the document."""
    paperless = paperless_factory(settings)
    try:
        # bulk_edit answers an unknown id with a 400; the lookup keeps it a 404.
        await run_blocking(lambda: paperless.get_document(document_id))
        await run_blocking(
            lambda: paperless.modify_tags(
                document_id,
                add=[add_tag],
                remove=[] if remove_tag is None else [remove_tag],
            )
        )
    finally:
        paperless.close()


def _recent_searches(
    app_db: sqlite3.Connection, user: CurrentUser
) -> RecentSearchesResponse:
    """Read the user's search history from ``app.db``."""
    rows = recent_search_store.list_for_user(app_db, user.id)
    return RecentSearchesResponse(
        searches=[
            RecentSearchEntry(query=row.query, created_at=row.created_at)
            for row in rows
        ]
    )
