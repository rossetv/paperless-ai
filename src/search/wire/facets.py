"""Pydantic wire models for facets, index stats, taxonomy, and recent searches.

The response shapes for ``GET /api/facets``, ``GET /api/stats``,
``GET /api/stats/public``, ``GET /api/recent-searches``, and the taxonomy
list/create endpoints, plus the converters from the store dataclasses and the
Paperless taxonomy items. A boundary module of the :mod:`search.wire` package
(``CODE_GUIDELINES.md`` §5.6).

Allowed deps: pydantic, store.models (FacetSet, IndexStats),
    common.paperless_types (PaperlessItem).
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from common.paperless_types import PaperlessItem
    from store.models import FacetSet, IndexStats


class TaxonomyEntryResponse(BaseModel):
    """A single taxonomy entry as returned to the browser."""

    kind: str
    id: int
    name: str


class FacetsResponse(BaseModel):
    """Response body for GET /api/facets."""

    correspondents: list[TaxonomyEntryResponse]
    document_types: list[TaxonomyEntryResponse]
    tags: list[TaxonomyEntryResponse]
    earliest: str | None
    latest: str | None


class StatsResponse(BaseModel):
    """Response body for GET /api/stats."""

    document_count: int
    chunk_count: int
    last_reconcile_at: str | None
    embedding_model: str | None


class PublicStatsResponse(BaseModel):
    """Response body for ``GET /api/stats/public`` — splash counts only."""

    document_count: int
    chunk_count: int


class RecentSearchEntry(BaseModel):
    """One entry in GET /api/recent-searches — a single past search."""

    query: str
    created_at: str


class RecentSearchesResponse(BaseModel):
    """Response body for GET /api/recent-searches — the user's history."""

    searches: list[RecentSearchEntry]


class TaxonomyItemResponse(BaseModel):
    """A correspondent, document type, or tag, as exposed to the SPA."""

    id: int
    name: str
    document_count: int = 0


class TaxonomyCreateRequest(BaseModel):
    """Body for ``POST /api/correspondents`` | ``/api/document-types`` | ``/api/tags``."""

    name: str


def to_facets_response(facets: FacetSet) -> FacetsResponse:
    """Convert a :class:`~store.models.FacetSet` to the wire model.

    Args:
        facets: The frozen dataclass from :meth:`~store.reader.StoreReader.list_facets`.

    Returns:
        A :class:`FacetsResponse` ready to serialise as JSON.
    """
    return FacetsResponse(
        correspondents=[
            TaxonomyEntryResponse(kind=e.kind, id=e.id, name=e.name)
            for e in facets.correspondents
        ],
        document_types=[
            TaxonomyEntryResponse(kind=e.kind, id=e.id, name=e.name)
            for e in facets.document_types
        ],
        tags=[
            TaxonomyEntryResponse(kind=e.kind, id=e.id, name=e.name)
            for e in facets.tags
        ],
        earliest=facets.earliest,
        latest=facets.latest,
    )


def to_stats_response(stats: IndexStats) -> StatsResponse:
    """Convert an :class:`~store.models.IndexStats` to the wire model.

    Args:
        stats: The frozen dataclass from :meth:`~store.reader.StoreReader.get_stats`.

    Returns:
        A :class:`StatsResponse` ready to serialise as JSON.
    """
    return StatsResponse(
        document_count=stats.document_count,
        chunk_count=stats.chunk_count,
        last_reconcile_at=stats.last_reconcile_at,
        embedding_model=stats.embedding_model,
    )


def _paperless_item_to_response(item: PaperlessItem) -> TaxonomyItemResponse:
    """Convert one Paperless taxonomy item to the wire shape.

    The Paperless API exposes the usage count under one of three field names
    depending on version — ``document_count`` / ``documents_count`` /
    ``documents`` (the last being a list of document ids).  We accept all three
    and coerce strings to int defensively.  When only a ``documents`` list is
    present we report 0: the list may be truncated on listing endpoints and
    inferring the count from it would be misleading.

    Args:
        item: A :class:`~common.paperless_types.PaperlessItem` dict as
            returned by :meth:`~common.paperless.PaperlessClient.list_correspondents`
            and its siblings.

    Returns:
        A :class:`TaxonomyItemResponse` ready to serialise as JSON.
    """
    raw: object = item.get("document_count")
    if raw is None:
        raw = item.get("documents_count")
    if raw is None:
        # ``documents`` is a list of referencing document ids; we intentionally
        # treat this as an unknown count rather than inferring len(list).
        raw = 0
    if isinstance(raw, str):
        count = int(raw) if raw.isdigit() else 0
    elif isinstance(raw, int):
        count = raw
    else:
        count = 0
    return TaxonomyItemResponse(id=item["id"], name=item["name"], document_count=count)
