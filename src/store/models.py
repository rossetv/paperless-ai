"""Frozen dataclasses for every value that crosses the store boundary.

Raw ``sqlite3.Row`` objects never leave the store.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndexState:
    """A single entry returned by StoreWriter.get_index_state().

    Attributes:
        modified: Last known Paperless modification, normalised UTC ISO-8601.
        content_hash: SHA-256 of the document's OCR content at index time.
    """

    modified: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    """Structured document metadata; input to upsert_document / update_metadata.

    ``created`` and ``modified`` are normalised UTC ISO-8601; ``tag_ids`` is
    stored as a JSON array; ``content_hash`` is the SHA-256 of the OCR content.
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

    ``page_hint`` is the estimated source page for citations, or None when the
    OCR output had no page marker.
    """

    chunk_index: int
    text: str
    page_hint: int | None
    embedding: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class TaxonomyEntry:
    """A taxonomy row; *kind* is 'correspondent', 'document_type', or 'tag'."""

    kind: str
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ChunkHit:
    """One chunk with its relevance score.

    ``chunk_id`` equals the ``chunks_fts`` rowid. ``score`` is the cosine
    distance (vector search) or raw BM25 rank (keyword search); lower is better
    for both.
    """

    chunk_id: int
    document_id: int
    text: str
    page_hint: int | None
    score: float


@dataclass(frozen=True, slots=True)
class FailedDocument:
    """A document the indexer has failed to index, for the Index dashboard.

    Read from the ``failed_documents`` map in meta. ``title`` is ``None`` when
    the document failed before it was ever stored; ``failure_count`` counts
    consecutive failed cycles.
    """

    document_id: int
    title: str | None
    failure_count: int


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    """A documents row joined to taxonomy display names."""

    id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    tags: tuple[str, ...]
    created: str | None


@dataclass(frozen=True, slots=True)
class FacetSet:
    """Taxonomy entries in the index plus the created-date range, for the UI."""

    correspondents: tuple[TaxonomyEntry, ...]
    document_types: tuple[TaxonomyEntry, ...]
    tags: tuple[TaxonomyEntry, ...]
    earliest: str | None
    latest: str | None


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Optional filters applied as SQL WHERE clauses *before* ranking.

    None (or an empty ``tag_ids``) means no restriction. ``date_from`` and
    ``date_to`` are inclusive ``YYYY-MM-DD`` bounds on ``documents.created``;
    every id in ``tag_ids`` must be present.
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
        last_reconcile_at: When the last successful cycle ran, or None. Rewritten
            every cycle, including no-op ones.
        latest_indexed_at: ``MAX(documents.indexed_at)``, or None on an empty
            index. It moves on any content or metadata upsert even when counts do
            not, so the result cache keys on it to drop stale answers.
    """

    document_count: int
    chunk_count: int
    last_reconcile_at: str | None
    embedding_model: str | None
    latest_indexed_at: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    """One document row for the Library browse list.

    Like :class:`IndexedDocument` plus ``page_count``, which the search-result
    shape does not need.
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

    Filter fields mean the same as in :class:`SearchFilters`; ``text`` is a
    case-insensitive substring of the title, correspondent or document type.
    ``sort`` is ``'created'``, ``'title'`` or ``'indexed_at'`` (date added) and
    is validated by the reader; the caller supplies sane pagination.
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
    """One page of Library browse results; *total* ignores pagination."""

    documents: tuple[DocumentSummary, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class KeywordHit:
    """One document matched by a keyword (FTS) search.

    Attributes:
        snippet: Excerpt from the best-matching chunk, or None for a filter-only
            browse.
        rank: Best (lowest) BM25 rank across the document's chunks; 0.0 for a
            filter-only browse.
    """

    document: DocumentSummary
    snippet: str | None
    rank: float


@dataclass(frozen=True, slots=True)
class KeywordPage:
    """One page of keyword hits, strongest first; *total* ignores pagination."""

    hits: tuple[KeywordHit, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class FilterFacet:
    """A taxonomy entry plus the count of indexed documents carrying it (may be 0)."""

    id: int
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class FilterCatalog:
    """Every filterable value in the index with counts, ordered by name, plus the
    created-date range (None when no document is dated)."""

    correspondents: tuple[FilterFacet, ...]
    document_types: tuple[FilterFacet, ...]
    tags: tuple[FilterFacet, ...]
    earliest: str | None
    latest: str | None
