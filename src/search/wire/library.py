"""Pydantic wire models for the Library API (web-redesign §5).

The document-browse request/response shapes for ``GET /api/documents`` and
``PATCH /api/documents/{id}`` plus the converters to the store browse query and
back to the wire envelope. A boundary module of the :mod:`search.wire` package
(``CODE_GUIDELINES.md`` §5.6).

Allowed deps: pydantic, store.models (DocumentBrowseQuery, DocumentSummary).
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from store.models import DocumentBrowseQuery, DocumentSummary

if TYPE_CHECKING:
    from store.models import DocumentPage

# The maximum Library page size accepted by ``GET /api/documents``.  Bounds
# the row count one request can pull from the index and the JSON payload
# size; the Library UI's pager never asks for more.  Applied at the HTTP
# boundary via ``Query(le=MAX_PAGE_SIZE)`` and re-asserted in the parser.
MAX_PAGE_SIZE = 100

# The maximum ``page`` number accepted by ``GET /api/documents``.  Without
# this bound a caller can send ``page=9_999_999_999`` producing a 9.9e11-row
# ``OFFSET`` that holds the StoreReader lock for a measurable duration on every
# query.  10 000 × 100 (MAX_PAGE_SIZE) = 1 000 000 rows — far more than any
# realistic Paperless instance.
MAX_PAGE_NUMBER = 10_000

# The public ``sort`` query-parameter enum for ``GET /api/documents``. Enforced
# at the FastAPI ``Query`` boundary (``search.routes``) so an out-of-set value is
# a 422 before any handler runs; :func:`to_document_browse_query` then trusts the
# narrowed type and needs no runtime guard (SRCH-11, CODE_GUIDELINES §6.1).
BrowseSort = Literal["created", "title", "added"]

# Maps each public ``sort`` value to the store's sort key. The public API
# exposes ``added`` (a friendly name); the store column is ``indexed_at``.
# ``created`` and ``title`` are identical on both sides. The mapping is total
# over :data:`BrowseSort`, so the lookup in :func:`to_document_browse_query`
# cannot miss.
_BROWSE_SORT_ALIASES: dict[BrowseSort, str] = {
    "created": "created",
    "title": "title",
    "added": "indexed_at",
}


class DocumentSummaryResponse(BaseModel):
    """One document in the Library list (web-redesign §5).

    The full per-document payload the Library card renders: identity, the
    resolved taxonomy display names, the document date, the tag names, the
    page count, and the deep-link URL into Paperless. The ``paperless_url``
    field makes :class:`DocumentSummaryResponse` shape-compatible with
    :class:`~search.wire.SourceDocumentResponse` from the perspective of the
    frontend, so both Library cards and search-result cards can render the same
    open-in-Paperless link without conditional logic.
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
    """Response body for GET /api/documents — one page of the Library.

    Attributes:
        documents: The document summaries for this page, in sort order.
        total: The total number of documents matching the request's filters,
            ignoring pagination — drives the UI pager.
        page: The 1-based page number this response represents.
        page_size: The page size that produced this response.
    """

    documents: list[DocumentSummaryResponse]
    total: int
    page: int
    page_size: int


class DocumentPatchRequest(BaseModel):
    """Body for ``PATCH /api/documents/{id}``.

    Every field is optional — only fields present in the request are passed
    through to Paperless. An empty body is a valid no-op.

    ``title`` and ``notes`` are forwarded verbatim to Paperless, so they are
    length-bounded here: a supplied ``title`` is 1-512 characters (Paperless
    rejects an empty title); ``notes`` is capped at 8 KiB.
    """

    title: str | None = Field(default=None, min_length=1, max_length=512)
    correspondent_id: int | None = None
    document_type_id: int | None = None
    document_date: str | None = None
    tags: list[int] | None = None
    notes: str | None = Field(default=None, max_length=8192)
    archive_serial_number: int | None = None


def to_document_summary_response(
    summary: DocumentSummary, *, paperless_url: str
) -> DocumentSummaryResponse:
    """Convert one store :class:`~store.models.DocumentSummary` to the wire model.

    The explicit, tested boundary conversion (``CODE_GUIDELINES.md`` §5.6).
    *paperless_url* is the fully-qualified deep-link into Paperless for this
    document; callers construct it from ``settings.PAPERLESS_URL`` so this
    function remains free of I/O and configuration knowledge.

    Args:
        summary: The store dataclass to convert.
        paperless_url: The fully-qualified Paperless deep-link URL for the
            document, e.g. ``https://paperless.example/documents/42/``.

    Returns:
        A :class:`DocumentSummaryResponse` ready to serialise as JSON.
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

    The explicit, tested boundary conversion (``CODE_GUIDELINES.md`` §5.6):
    no Pydantic model leaks into the store layer, no store dataclass leaks
    into the HTTP response.  *page_number* and *page_size* are supplied by the
    handler (which derived them from the validated query parameters) rather
    than recomputed here, so this function is a pure field copy.

    *paperless_base_url* is used to construct the ``paperless_url`` deep-link
    for each document; the caller strips any trailing slash before passing it
    so the per-document URLs are consistently formatted.

    Args:
        page: The browse page from
            :meth:`~store.reader.StoreReader.list_documents`.
        page_number: The 1-based page number this response represents.
        page_size: The page size that produced *page*.
        paperless_base_url: The Paperless base URL with no trailing slash,
            e.g. ``https://paperless.example``. Prepended to each document's
            ``/documents/{id}/`` path.

    Returns:
        A :class:`DocumentListResponse` ready to serialise as JSON.
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
    """Map validated HTTP query parameters to a store browse query.

    The single converter from the ``GET /api/documents`` query string to
    :class:`~store.models.DocumentBrowseQuery`.  *page* and *page_size* are
    already range-checked by FastAPI's ``Query`` constraints on the handler;
    this function trusts those bounds and derives the zero-based ``offset``.

    The public ``sort`` value is translated through
    :data:`_BROWSE_SORT_ALIASES` — the API name ``added`` maps to the store
    column ``indexed_at``; ``created`` and ``title`` pass through. ``sort`` is a
    :data:`BrowseSort`, validated at the ``Query`` boundary, so the lookup is
    total and cannot miss — no runtime guard is needed (SRCH-11, §6.1).

    Args:
        page: The 1-based page number (FastAPI enforces ``>= 1``).
        page_size: Rows per page (FastAPI enforces ``1..MAX_PAGE_SIZE``).
        sort: One of ``created``, ``title``, ``added`` (the :data:`BrowseSort`
            enum, enforced at the HTTP boundary).
        descending: True for a descending sort, False for ascending.
        text: Optional in-library text query, or None.
        date_from: Optional inclusive ISO-8601 lower date bound, or None.
        date_to: Optional inclusive ISO-8601 upper date bound, or None.
        correspondent_id: Optional correspondent filter id, or None.
        document_type_id: Optional document-type filter id, or None.
        tag_ids: Tag-id filter list; empty means no tag restriction.

    Returns:
        The :class:`~store.models.DocumentBrowseQuery` for the store reader.
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
