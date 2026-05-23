"""The StoreReader facade — the read-side interface to the search index.

:class:`StoreReader` owns the index connection and the thread lock that
serialises queries across the search server's request threads.  The query
implementations live in the three sibling concept-modules — ranked retrieval
in :mod:`store.reader._ranked`, look-ups and introspection in
:mod:`store.reader._lookups`, and the Library browse in
:mod:`store.reader._browse` — and this class is a thin facade that holds the
shared state and delegates each call.

DB reads are fast at this scale (≤10k documents); a single lock serialising
them is correct and keeps the concurrency model simple (SPEC §3.2,
CODE_GUIDELINES §8.4).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Sequence

from common.config import Settings
from store.models import (
    ChunkHit,
    DocumentBrowseQuery,
    DocumentPage,
    FailedDocument,
    FacetSet,
    IndexedDocument,
    IndexStats,
    SearchFilters,
    TaxonomyEntry,
)
from store.reader import _browse, _lookups, _ranked
from store.schema import connect


class StoreReader:
    """Read API for the SQLite search index.

    A single instance is shared across the search server's request threads; an
    internal Lock serialises every query so concurrent callers do not race on
    the connection (SPEC §3.2, CODE_GUIDELINES §8.4).  The class exposes no
    write method — read-only access is a structural property of the API
    surface, backed by the indexer's single-writer flock.

    Raises:
        StoreError: Any sqlite3.Error encountered during a query is wrapped in
            StoreError (with ``from``) and re-raised.
    """

    def __init__(self, settings: Settings) -> None:
        """Open a connection to the index database.

        Args:
            settings: Application settings; ``INDEX_DB_PATH`` is used.
        """
        self._conn = connect(settings.INDEX_DB_PATH)
        # Serialises all queries across threads (SPEC §3.2, CODE_GUIDELINES §8.4).
        self._query_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Ranked retrieval
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Look-ups and introspection
    # ------------------------------------------------------------------

    def get_documents(self, ids: Iterable[int]) -> list[IndexedDocument]:
        """Return IndexedDocument objects for the given document ids.

        See :func:`store.reader._lookups.get_documents`.
        """
        return _lookups.get_documents(self._conn, self._query_lock, ids)

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
        """Run ``PRAGMA quick_check`` on the database.

        See :func:`store.reader._lookups.quick_check`.
        """
        return _lookups.quick_check(self._conn, self._query_lock)

    # ------------------------------------------------------------------
    # Library browse
    # ------------------------------------------------------------------

    def list_documents(self, query: DocumentBrowseQuery) -> DocumentPage:
        """List documents for the Library with pagination, sorting and filters.

        See :func:`store.reader._browse.list_documents`.
        """
        return _browse.list_documents(self._conn, self._query_lock, query)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
