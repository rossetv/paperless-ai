"""The StoreReader facade: owns the connection and lock, delegates each query."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Sequence

from common.config import Settings
from store.models import (
    ChunkHit,
    DocumentBrowseQuery,
    DocumentPage,
    DocumentSummary,
    FailedDocument,
    FacetSet,
    FilterCatalog,
    IndexedDocument,
    IndexStats,
    KeywordHit,
    KeywordPage,
    SearchFilters,
    TaxonomyEntry,
)
from store.reader import _browse, _lookups, _ranked
from store.schema import connect


# Health probes are frequent and unauthenticated; a full integrity scan per probe
# would contend with searches for the query lock.
_QUICK_CHECK_TTL_SECONDS = 30.0


class StoreReader:
    """Read API for the SQLite search index.

    One instance is shared across the search server's request threads. A single
    lock serialises every query; reads are fast at this scale (about 10k
    documents), so that keeps concurrency simple. Every ``sqlite3.Error`` is
    re-raised as :class:`StoreError`.
    """

    def __init__(
        self, settings: Settings, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Open a connection to the index database."""
        self._conn = connect(settings.INDEX_DB_PATH)
        self._query_lock = threading.Lock()
        self._clock = clock
        self._quick_check_lock = threading.Lock()
        self._quick_check_cache: tuple[float, bool] | None = None

    def vector_search(
        self,
        query_embedding: Sequence[float],
        k: int,
        filters: SearchFilters,
    ) -> list[ChunkHit]:
        """Exact scalar-distance KNN over the SQL-filtered candidate set.

        See :func:`store.reader._ranked.vector_search`.
        """
        return _ranked.vector_search(
            self._conn, self._query_lock, query_embedding, k, filters
        )

    def keyword_search(
        self,
        terms: Sequence[str],
        k: int,
        filters: SearchFilters,
    ) -> list[ChunkHit]:
        """FTS5 BM25 search over chunks_fts with the same pre-ranking filters.

        See :func:`store.reader._ranked.keyword_search`.
        """
        return _ranked.keyword_search(self._conn, self._query_lock, terms, k, filters)

    def keyword_document_search(
        self,
        terms: Sequence[str],
        filters: SearchFilters,
        limit: int,
        offset: int,
    ) -> KeywordPage:
        """FTS5 keyword search grouped to ranked documents, with snippets.

        See :func:`store.reader._ranked.keyword_document_search`.
        """
        rows, total = _ranked.keyword_document_search(
            self._conn, self._query_lock, terms, filters, limit, offset
        )
        hits: list[KeywordHit] = []
        for doc_id, text, rank in rows:
            summary = _lookups.get_document_summary(
                self._conn, self._query_lock, doc_id
            )
            if summary is None:
                # Pruned between the FTS query and this lookup; skip it.
                continue
            snippet = " ".join(text.split())[:280]
            hits.append(KeywordHit(document=summary, snippet=snippet, rank=rank))
        return KeywordPage(hits=tuple(hits), total=total, offset=offset, limit=limit)

    def get_documents(self, ids: Iterable[int]) -> list[IndexedDocument]:
        """Return IndexedDocument objects for the given document ids.

        See :func:`store.reader._lookups.get_documents`.
        """
        return _lookups.get_documents(self._conn, self._query_lock, ids)

    def get_document_summary(self, document_id: int) -> DocumentSummary | None:
        """Return the DocumentSummary for one document id, or None if absent.

        See :func:`store.reader._lookups.get_document_summary`.
        """
        return _lookups.get_document_summary(self._conn, self._query_lock, document_id)

    def get_chunks(self, ids: Iterable[int]) -> list[ChunkHit]:
        """Return ChunkHit objects for the given chunk ids.

        See :func:`store.reader._lookups.get_chunks`.
        """
        return _lookups.get_chunks(self._conn, self._query_lock, ids)

    def get_taxonomy(self, kind: str) -> list[TaxonomyEntry]:
        """Return every taxonomy entry of the given *kind*, ordered by name.

        See :func:`store.reader._lookups.get_taxonomy`.
        """
        return _lookups.get_taxonomy(self._conn, self._query_lock, kind)

    def list_facets(self) -> FacetSet:
        """Return all taxonomy entries grouped by kind, plus the date range.

        See :func:`store.reader._lookups.list_facets`.
        """
        return _lookups.list_facets(self._conn, self._query_lock)

    def list_filters_with_counts(self) -> FilterCatalog:
        """Return every taxonomy entry with its document count + date range.

        See :func:`store.reader._lookups.list_filters_with_counts`.
        """
        return _lookups.list_filters_with_counts(self._conn, self._query_lock)

    def get_stats(self) -> IndexStats:
        """Return summary statistics for the search index.

        See :func:`store.reader._lookups.get_stats`.
        """
        return _lookups.get_stats(self._conn, self._query_lock)

    def get_failed_documents(self) -> list[FailedDocument]:
        """Return the documents the indexer has failed to index.

        See :func:`store.reader._lookups.get_failed_documents`.
        """
        return _lookups.get_failed_documents(self._conn, self._query_lock)

    def quick_check(self) -> bool:
        """Run ``PRAGMA quick_check`` on the database, cached for 30 seconds.

        See :func:`store.reader._lookups.quick_check`. A failing result is
        cached like a passing one; an error raised by the check is not.
        """
        with self._quick_check_lock:
            now = self._clock()
            cached = self._quick_check_cache
            if cached is not None and now - cached[0] < _QUICK_CHECK_TTL_SECONDS:
                return cached[1]
            result = _lookups.quick_check(self._conn, self._query_lock)
            self._quick_check_cache = (now, result)
            return result

    def list_documents(self, query: DocumentBrowseQuery) -> DocumentPage:
        """List documents for the Library with pagination, sorting and filters.

        See :func:`store.reader._browse.list_documents`.
        """
        return _browse.list_documents(self._conn, self._query_lock, query)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
