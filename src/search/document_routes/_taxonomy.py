"""The taxonomy ``/api`` routes — correspondents, document types, tags.

Each taxonomy has a list (``GET``) and a create (``POST``) endpoint, all
proxying to the per-request :class:`~common.paperless.PaperlessClient`:

- ``GET  /api/correspondents``  · ``POST /api/correspondents``
- ``GET  /api/document-types``  · ``POST /api/document-types``
- ``GET  /api/tags``            · ``POST /api/tags``

Listing needs Read-only or above; creating needs Member or above. Each request
builds its own Paperless client, because it is not thread-safe.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends

from search.deps import require_api_scope, require_api_scope_member
from search.offload import run_blocking
from search.wire import (
    TaxonomyCreateRequest,
    TaxonomyItemResponse,
    paperless_item_to_response,
)

if TYPE_CHECKING:
    from common.config import Settings
    from common.paperless import PaperlessClient

log = structlog.get_logger(__name__)


def register_taxonomy_routes(
    router: APIRouter,
    current_settings: Callable[[], Settings],
    *,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> None:
    """Register the six taxonomy list/create routes on *router*."""

    @router.get(
        "/api/correspondents",
        dependencies=[Depends(require_api_scope)],
    )
    async def list_correspondents() -> list[TaxonomyItemResponse]:
        """Return all Paperless correspondents with their document counts."""
        paperless = paperless_factory(await run_blocking(current_settings))
        try:
            items = await run_blocking(paperless.list_correspondents)
        finally:
            paperless.close()
        return [paperless_item_to_response(i) for i in items]

    @router.post(
        "/api/correspondents",
        status_code=201,
        dependencies=[Depends(require_api_scope_member)],
    )
    async def create_correspondent(body: TaxonomyCreateRequest) -> TaxonomyItemResponse:
        """Create a new Paperless correspondent and return it."""
        paperless = paperless_factory(await run_blocking(current_settings))
        try:
            created = await run_blocking(
                lambda: paperless.create_correspondent(body.name)
            )
        finally:
            paperless.close()
        return paperless_item_to_response(created)

    @router.get(
        "/api/document-types",
        dependencies=[Depends(require_api_scope)],
    )
    async def list_document_types() -> list[TaxonomyItemResponse]:
        """Return all Paperless document types with their document counts."""
        paperless = paperless_factory(await run_blocking(current_settings))
        try:
            items = await run_blocking(paperless.list_document_types)
        finally:
            paperless.close()
        return [paperless_item_to_response(i) for i in items]

    @router.post(
        "/api/document-types",
        status_code=201,
        dependencies=[Depends(require_api_scope_member)],
    )
    async def create_document_type(body: TaxonomyCreateRequest) -> TaxonomyItemResponse:
        """Create a new Paperless document type and return it."""
        paperless = paperless_factory(await run_blocking(current_settings))
        try:
            created = await run_blocking(
                lambda: paperless.create_document_type(body.name)
            )
        finally:
            paperless.close()
        return paperless_item_to_response(created)

    @router.get(
        "/api/tags",
        dependencies=[Depends(require_api_scope)],
    )
    async def list_tags() -> list[TaxonomyItemResponse]:
        """Return all Paperless tags with their document counts."""
        paperless = paperless_factory(await run_blocking(current_settings))
        try:
            items = await run_blocking(paperless.list_tags)
        finally:
            paperless.close()
        return [paperless_item_to_response(i) for i in items]

    @router.post(
        "/api/tags",
        status_code=201,
        dependencies=[Depends(require_api_scope_member)],
    )
    async def create_tag(body: TaxonomyCreateRequest) -> TaxonomyItemResponse:
        """Create a new Paperless tag and return it."""
        paperless = paperless_factory(await run_blocking(current_settings))
        try:
            created = await run_blocking(lambda: paperless.create_tag(body.name))
        finally:
            paperless.close()
        return paperless_item_to_response(created)
