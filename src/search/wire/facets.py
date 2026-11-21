"""Wire models for facets, index stats, taxonomy and recent searches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

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
    """Body for ``POST /api/correspondents`` | ``/api/document-types`` | ``/api/tags``.

    ``name`` is forwarded to Paperless, so it is capped at Paperless's own
    255-character limit.
    """

    name: str = Field(min_length=1, max_length=255)


def to_facets_response(facets: FacetSet) -> FacetsResponse:
    """Convert a :class:`~store.models.FacetSet` to the wire model."""
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
    """Convert an :class:`~store.models.IndexStats` to the wire model."""
    return StatsResponse(
        document_count=stats.document_count,
        chunk_count=stats.chunk_count,
        last_reconcile_at=stats.last_reconcile_at,
        embedding_model=stats.embedding_model,
    )


def paperless_item_to_response(item: PaperlessItem) -> TaxonomyItemResponse:
    """Convert one Paperless taxonomy item to the wire shape.

    Paperless versions name the usage count ``document_count``,
    ``documents_count`` or ``documents`` (a list of ids). With only the list
    the count is 0, since the list may be truncated on listing endpoints.
    """
    raw: object = item.get("document_count")
    if raw is None:
        raw = item.get("documents_count")
    if raw is None:
        raw = 0
    if isinstance(raw, str):
        count = int(raw) if raw.isdigit() else 0
    elif isinstance(raw, int):
        count = raw
    else:
        count = 0
    return TaxonomyItemResponse(id=item["id"], name=item["name"], document_count=count)
