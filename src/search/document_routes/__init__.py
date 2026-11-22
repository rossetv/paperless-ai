"""The document ``/api`` router: PDF/thumbnail proxy, documents, taxonomy.

:class:`~common.paperless.PaperlessClient` is imported here so tests can patch
``search.document_routes.PaperlessClient`` to a stub.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from common.paperless import PaperlessClient
from search.document_routes._documents import register_document_routes
from search.document_routes._proxy import register_proxy_routes
from search.document_routes._taxonomy import register_taxonomy_routes

if TYPE_CHECKING:
    from collections.abc import Callable

    from common.config import Settings
    from store.reader import StoreReader

__all__ = ["build_document_router"]


def _default_paperless_factory(settings: Settings) -> PaperlessClient:
    """Build a real :class:`PaperlessClient` from *settings*."""
    return PaperlessClient(settings)


def build_document_router(
    current_settings: Callable[[], Settings],
    *,
    store_reader: StoreReader,
    paperless_factory: Callable[[Settings], PaperlessClient] = (
        _default_paperless_factory
    ),
) -> APIRouter:
    """Build the ``/api`` document and search-history router.

    *current_settings* is called per request, so a saved Paperless URL, token
    or tag id applies without a restart. *paperless_factory* builds the
    :class:`PaperlessClient` for a request; tests inject a stub.
    """
    router = APIRouter()
    register_proxy_routes(router, current_settings, paperless_factory=paperless_factory)
    register_document_routes(
        router,
        current_settings,
        store_reader=store_reader,
        paperless_factory=paperless_factory,
    )
    register_taxonomy_routes(
        router, current_settings, paperless_factory=paperless_factory
    )
    return router
