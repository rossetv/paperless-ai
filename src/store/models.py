"""Frozen dataclasses for the store's public API surface.

Every value that crosses the store boundary travels in one of these shapes.
Raw sqlite3.Row objects never leave src/store/.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndexState:
    """A single entry returned by StoreWriter.get_index_state().

    Attributes:
        modified: Normalised UTC ISO-8601 timestamp of the last known
            Paperless modification.
        content_hash: SHA-256 of the document's OCR content at index time.
    """

    modified: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    """Structured document metadata; input to upsert_document / update_metadata.

    Attributes:
        id: The Paperless document id (INTEGER PRIMARY KEY in documents).
        title: Human-readable title from Paperless, or None if unset.
        correspondent_id: FK-by-value into the taxonomy table; None if unset.
        document_type_id: FK-by-value into the taxonomy table; None if unset.
        tag_ids: Tuple of tag ids; stored as a JSON array in the DB.
        created: Document date normalised to UTC ISO-8601; None if unset.
        modified: Paperless 'modified' field normalised to UTC ISO-8601.
        content_hash: SHA-256 hex digest of the OCR content.
        page_count: Number of pages; None if unknown.
    """

    id: int
    title: str | None
    correspondent_id: int | None
    document_type_id: int | None
    tag_ids: tuple[int, ...]
    created: str | None
    modified: str
    content_hash: str
    page_count: int | None


@dataclass(frozen=True, slots=True)
class ChunkInput:
    """One text chunk awaiting storage, produced by the chunker.

    Attributes:
        chunk_index: Zero-based position within the parent document.
        text: The chunk's text content.
        page_hint: Estimated source page number for citations; None if
            no page marker was found in the OCR output.
        embedding: The float32 vector produced by the embedding client.
    """

    chunk_index: int
    text: str
    page_hint: int | None
    embedding: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class TaxonomyEntry:
    """A single row from the taxonomy table.

    Attributes:
        kind: One of 'correspondent', 'document_type', or 'tag'.
        id: The Paperless id for this entity.
        name: The current display name (refreshed each reconciliation cycle).
    """

    kind: str
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ChunkHit:
    """A single search hit — one chunk with its relevance score.

    Attributes:
        chunk_id: The chunks.id (== chunks_fts rowid) for this hit.
        document_id: The parent document's id.
        text: The chunk text.
        page_hint: Source page number, or None if unavailable.
        score: Cosine distance for vector search; BM25 rank for keyword search.
            Lower is better for cosine distance; higher is better for BM25.
    """

    chunk_id: int
    document_id: int
    text: str
    page_hint: int | None
    score: float


@dataclass(frozen=True, slots=True)
class FailedDocument:
    """A document the indexer has failed to index, for the Index dashboard.

    Sourced from the ``failed_documents`` map in ``index.db`` meta — the
    indexer's record of documents whose indexing raised (web-redesign spec
    §5, Wave 6). The indexer re-attempts every entry each cycle until it
    succeeds or is dead-lettered.

    Attributes:
        document_id: The Paperless document id.
        title: The document's title from the index, or ``None`` when the
            document has no indexed row (it failed before it was ever
            stored).
        failure_count: How many consecutive cycles the document has failed.
    """

    document_id: int
    title: str | None
    failure_count: int


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    """A documents row joined to taxonomy display names.

    Attributes:
        id: The Paperless document id.
        title: Document title, or None.
        correspondent: Resolved correspondent name, or None.
        document_type: Resolved document-type name, or None.
        tags: Tuple of tag names (resolved from taxonomy).
        created: Document date in normalised UTC ISO-8601, or None.
    """

    id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    tags: tuple[str, ...]
    created: str | None


@dataclass(frozen=True, slots=True)
class FacetSet:
    """Aggregated facet data for the search UI.

    Attributes:
        correspondents: All correspondent taxonomy entries present in the index.
        document_types: All document-type taxonomy entries present in the index.
        tags: All tag taxonomy entries present in the index.
        earliest: Earliest document creation date in the index (ISO-8601), or None.
        latest: Latest document creation date in the index (ISO-8601), or None.
    """

    correspondents: tuple[TaxonomyEntry, ...]
    document_types: tuple[TaxonomyEntry, ...]
    tags: tuple[TaxonomyEntry, ...]
    earliest: str | None
    latest: str | None


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Optional pre-ranking filters for vector_search and keyword_search.

    A store-boundary input shape: the search pipeline constructs it and hands
    it to the StoreReader, which applies the non-default fields as SQL WHERE
    clauses on the documents table *before* ranking.  All fields default to
    "no restriction", so an all-default SearchFilters leaves the candidate set
    as the full document table.

    Attributes:
        date_from: Lower bound on documents.created (inclusive, ISO-8601
            string, lexicographic comparison).  None means no lower bound.
        date_to: Upper bound on documents.created (inclusive, ISO-8601
            string, lexicographic comparison).  None means no upper bound.
        correspondent_id: Exact match on documents.correspondent_id.
            None means no restriction.
        document_type_id: Exact match on documents.document_type_id.
            None means no restriction.
        tag_ids: Every id in the tuple must appear in documents.tag_ids.
            An empty tuple means no restriction.
    """

    date_from: str | None
    date_to: str | None
    correspondent_id: int | None
    document_type_id: int | None
    tag_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class IndexStats:
    """Summary statistics for the search index.

    Attributes:
        document_count: Number of indexed documents.
        chunk_count: Total number of stored chunks.
        last_reconcile_at: ISO-8601 timestamp of the last successful
            reconciliation cycle, or None if reconciliation has never run.
        embedding_model: The embedding model name recorded in meta, or None.
    """

    document_count: int
    chunk_count: int
    last_reconcile_at: str | None
    embedding_model: str | None


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    """One document row for the Library browse list (web-redesign §5).

    A documents-table row joined to taxonomy display names, like
    :class:`IndexedDocument`, but additionally carrying ``page_count`` —
    the Library list shows a page count per document and ``IndexedDocument``
    (the search-result shape) deliberately omits it.  A distinct shape keeps
    each read's projection honest rather than overloading one dataclass.

    Attributes:
        id: The Paperless document id.
        title: Document title, or None.
        correspondent: Resolved correspondent name, or None.
        document_type: Resolved document-type name, or None.
        tags: Tuple of tag names resolved from taxonomy.
        created: Document date in normalised UTC ISO-8601, or None.
        page_count: Number of pages, or None when unknown.
    """

    id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    tags: tuple[str, ...]
    created: str | None
    page_count: int | None


@dataclass(frozen=True, slots=True)
class DocumentBrowseQuery:
    """Parameters for :meth:`~store.reader.StoreReader.list_documents`.

    A store-boundary input shape (like :class:`SearchFilters`): the search
    server constructs it from validated HTTP query parameters and hands it to
    the reader.  Every filter field defaults to "no restriction" semantics;
    the caller is responsible for supplying sane pagination and sort values.

    Attributes:
        text: Optional case-insensitive substring matched against the
            document title, correspondent name, and document-type name.
            None or empty means no text restriction.
        date_from: Inclusive lower bound on ``documents.created`` (ISO-8601
            string, lexicographic comparison).  None means no lower bound.
        date_to: Inclusive upper bound on ``documents.created``.  None means
            no upper bound.
        correspondent_id: Exact match on ``documents.correspondent_id``.
            None means no restriction.
        document_type_id: Exact match on ``documents.document_type_id``.
            None means no restriction.
        tag_ids: Every id in the tuple must appear in ``documents.tag_ids``.
            An empty tuple means no restriction.
        sort: The sort column — one of ``'created'``, ``'title'``, or
            ``'indexed_at'`` (date added).  Validated by the reader.
        descending: When True the sort is descending; when False, ascending.
        offset: Number of rows to skip (pagination); must be >= 0.
        limit: Maximum number of rows to return; must be > 0.
    """

    text: str | None
    date_from: str | None
    date_to: str | None
    correspondent_id: int | None
    document_type_id: int | None
    tag_ids: tuple[int, ...]
    sort: str
    descending: bool
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class DocumentPage:
    """One page of Library browse results (web-redesign §5).

    Attributes:
        documents: The document summaries for this page, in sort order.
        total: The total number of documents matching the query's filters,
            ignoring pagination — the count the UI's pager needs.
        offset: The offset that produced this page (echoed back).
        limit: The limit that produced this page (echoed back).
    """

    documents: tuple[DocumentSummary, ...]
    total: int
    offset: int
    limit: int
