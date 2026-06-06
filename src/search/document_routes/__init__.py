"""The document and search-history ``/api`` router for the search server.

This package, mounted by ``search/api.py`` alongside the search and account
routers, owns the Wave 2 backend endpoints that feed the redesigned search UI
(web-redesign §5): the document/PDF/thumbnail proxy, the per-user
recent-searches read, the taxonomy CRUD (correspondents / document types /
tags), and the pipeline re-queue endpoints.

It was a single 728-line module mixing those four concerns; it is now split one
concept per file (``CODE_GUIDELINES.md`` §3.1/§3.3), with this thin ``__init__``
re-exporting :func:`build_document_router` so ``from search.document_routes
import build_document_router`` is unchanged for every importer:

- :mod:`~search.document_routes._proxy` — the PDF/thumbnail streaming proxies
  and the shared ``_safe_stream`` body-with-cleanup generator.
- :mod:`~search.document_routes._taxonomy` — the six taxonomy list/create routes.
- :mod:`~search.document_routes._documents` — the single-document summary /
  patch / delete / re-queue routes and the recent-searches read.

:class:`~common.paperless.PaperlessClient` is imported here (not only in the
submodules) so the production factory below resolves it from this package
namespace — the proxy/thumb integration tests patch
``search.document_routes.PaperlessClient`` to a stub.

Allowed deps: fastapi, common (paperless, config), and the package's own
    private submodules (which carry the fastapi/starlette/httpx/appdb deps).
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
    """Build a real :class:`PaperlessClient` from *settings*.

    The production factory. Tests pass their own factory returning a stub, or
    patch ``search.document_routes.PaperlessClient`` so this factory builds the
    stub instead — so the router never makes a real Paperless call.
    """
    return PaperlessClient(settings)


def build_document_router(
    settings: Settings,
    *,
    store_reader: StoreReader,
    paperless_factory: Callable[[Settings], PaperlessClient] = (
        _default_paperless_factory
    ),
) -> APIRouter:
    """Build the ``/api`` document and search-history router (§5).

    Composes the proxy, single-document, and taxonomy routes onto one router,
    each concern registered by its own module. Every route keeps the same path,
    method, and auth guard it had before the package split.

    Args:
        settings: Application settings, forwarded to the Paperless client
            factory.
        store_reader: The store reader used by the document-summary route.
        paperless_factory: Builds the :class:`PaperlessClient` for a request.
            Defaults to the real client; tests inject a stub factory.

    Returns:
        A configured :class:`~fastapi.APIRouter`.
    """
    router = APIRouter()
    register_proxy_routes(router, settings, paperless_factory=paperless_factory)
    register_document_routes(
        router,
        settings,
        store_reader=store_reader,
        paperless_factory=paperless_factory,
    )
    register_taxonomy_routes(router, settings, paperless_factory=paperless_factory)
    return router
