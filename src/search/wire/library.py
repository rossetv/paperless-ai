"""Wire models for the Library endpoints (``/api/documents``) and converters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from store.models import DocumentBrowseQuery, DocumentSummary

if TYPE_CHECKING:
    from store.models import DocumentPage

# Bounds the rows and payload of one request; the Library pager never asks
# for more.
MAX_PAGE_SIZE = 100

# Without a bound a huge ``page`` makes an OFFSET that holds the StoreReader
# lock for a long time. 10 000 pages of 100 is far beyond any real archive.
MAX_PAGE_NUMBER = 10_000

# Enforced by FastAPI's ``Query``, so an unknown value is a 422 before any
# handler runs.
BrowseSort = Literal["created", "title", "added"]

# Public sort name to store sort key; total over :data:`BrowseSort`.
_BROWSE_SORT_ALIASES: dict[BrowseSort, str] = {
    "created": "created",
    "title": "title",
    "added": "indexed_at",
}


class DocumentSummaryResponse(BaseModel):
    """One document in the Library list.

    ``paperless_url`` matches :class:`~search.wire.SourceDocumentResponse`, so
    Library and search-result cards render the same Paperless link.
    """

    id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    created: str | None
    tags: list[str]
    page_count: int | None
    paperless_url: str


class DocumentListResponse(BaseModel):
    """Response body for GET /api/documents: one page of the Library.

    ``total`` counts every match, ignoring pagination; ``page`` is 1-based.
    """

    documents: list[DocumentSummaryResponse]
    total: int
    page: int
    page_size: int


class DocumentPatchRequest(BaseModel):
    """Body for ``PATCH /api/documents/{id}``.

    Only the fields present are passed to Paperless. ``title`` and ``notes``
    are forwarded verbatim, so they are length-bounded here; Paperless rejects
    an empty title.
    """

    title: str | None = Field(default=None, min_length=1, max_length=512)
    correspondent_id: int | None = None
    document_type_id: int | None = None
    document_date: str | None = None
    tags: list[int] | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=8192)
    archive_serial_number: int | None = None


def to_document_summary_response(
    summary: DocumentSummary, *, paperless_url: str
) -> DocumentSummaryResponse:
    """Convert one store :class:`~store.models.DocumentSummary` to the wire model.

    *paperless_url* is the full link, e.g.
    ``https://paperless.example/documents/42/``.
    """
    return DocumentSummaryResponse(
        id=summary.id,
        title=summary.title,
        correspondent=summary.correspondent,
        document_type=summary.document_type,
        created=summary.created,
        tags=list(summary.tags),
        page_count=summary.page_count,
        paperless_url=paperless_url,
    )


def to_document_list_response(
    page: DocumentPage,
    *,
    page_number: int,
    page_size: int,
    paperless_base_url: str,
) -> DocumentListResponse:
    """Convert a store :class:`~store.models.DocumentPage` to the wire model.

    *paperless_base_url* has no trailing slash, e.g.
    ``https://paperless.example``.
    """
    return DocumentListResponse(
        documents=[
            to_document_summary_response(
                s, paperless_url=f"{paperless_base_url}/documents/{s.id}/"
            )
            for s in page.documents
        ],
        total=page.total,
        page=page_number,
        page_size=page_size,
    )


def to_document_browse_query(
    *,
    page: int,
    page_size: int,
    sort: BrowseSort,
    descending: bool,
    text: str | None,
    date_from: str | None,
    date_to: str | None,
    correspondent_id: int | None,
    document_type_id: int | None,
    tag_ids: list[int],
) -> DocumentBrowseQuery:
    """Map validated ``GET /api/documents`` parameters to a store browse query.

    *page* (1-based) and *page_size* are range-checked by FastAPI. The date
    bounds are inclusive; an empty *tag_ids* means no tag restriction.
    """
    store_sort = _BROWSE_SORT_ALIASES[sort]
    return DocumentBrowseQuery(
        text=text,
        date_from=date_from,
        date_to=date_to,
        correspondent_id=correspondent_id,
        document_type_id=document_type_id,
        tag_ids=tuple(tag_ids),
        sort=store_sort,
        descending=descending,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
