"""Read API for the search index store.

StoreReader is the sole read-side interface to the SQLite search index.
The search pipeline and search server use it to run vector search, keyword
search, document look-ups, facet listing, and health checks.

Every query method acquires a threading.Lock around its connection use so
that the search server can call methods concurrently from multiple threads
on one shared StoreReader instance.  DB reads are fast at this scale
(≤10k documents); serialising them is correct and keeps the locking model
simple (SPEC §3.2, CODE_GUIDELINES §8.4).

No write method exists on this class.  Read-only access is enforced
structurally: the StoreReader API has no write surface, and the indexer's
flock makes it the sole writer (SPEC §3.2).

Allowed deps: sqlite3, sqlite_vec, store.schema, store.migrations, store.models,
    common.config.
Forbidden: imports from indexer/, search/, or any package above store/.
No HTTP, no LLM calls, no business logic.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import sqlite_vec  # type: ignore[import-untyped]  # no stubs shipped
import structlog

from common.config import Settings
from store.migrations import StoreError
from store.models import ChunkHit, FacetSet, IndexedDocument, IndexStats, TaxonomyEntry
from store.schema import connect

log = structlog.get_logger(__name__)

# Cosine-distance score returned for a chunk whose embedding is a zero-length
# blob or otherwise unreadable; used as a sentinel, never served to callers.
_FALLBACK_SCORE: float = 1.0


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Optional filters for vector_search and keyword_search.

    All fields default to "no restriction".  Only non-None / non-empty fields
    are applied as SQL WHERE clauses, so the candidate set is the full
    document table when SearchFilters is constructed with all-None values.

    The search pipeline imports this class from here; no other definition
    of SearchFilters exists in the codebase.

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


class StoreReader:
    """Read API for the SQLite search index.

    Owns all read queries against the index database.  A single instance is
    shared across the search server's request threads; an internal Lock
    serialises every query so concurrent callers do not race on the
    connection (SPEC §3.2, CODE_GUIDELINES §8.4).

    Raises:
        StoreError: Any sqlite3.Error encountered during a query is wrapped
            in StoreError (with ``from``) and re-raised.
    """

    def __init__(self, settings: Settings) -> None:
        """Open a connection to the index database.

        Args:
            settings: Application settings; ``INDEX_DB_PATH`` is used.
        """
        self._conn = connect(settings.INDEX_DB_PATH, read_only=True)
        # Serialises all queries across threads (SPEC §3.2, CODE_GUIDELINES §8.4).
        self._query_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Vector search
    # ------------------------------------------------------------------

    def vector_search(
        self,
        query_embedding: Sequence[float],
        k: int,
        filters: SearchFilters,
    ) -> list[ChunkHit]:
        """Exact scalar-distance KNN over the SQL-filtered candidate set.

        Applies *filters* as SQL WHERE clauses on *documents* before ranking
        by cosine distance, so filtered recall is exact — no "k rows returned,
        all filtered out" failure (SPEC §6.2).

        The query:
            SELECT c.id, c.document_id, c.text, c.page_hint,
                   vec_distance_cosine(c.embedding, :q) AS distance
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE <resolved filters on d>
            ORDER BY distance
            LIMIT :k

        Args:
            query_embedding: The float32 query vector (must match stored dimensions).
            k: Maximum number of results to return.
            filters: Pre-ranking filter; applied as SQL WHERE on documents.

        Returns:
            Up to *k* ChunkHit objects ordered by ascending cosine distance
            (nearest first).  ChunkHit.score is the cosine distance.

        Raises:
            StoreError: On SQLite error.
        """
        query_blob = sqlite_vec.serialize_float32(list(query_embedding))
        where_clause, params = _build_filters(filters)
        sql = f"""
            SELECT c.id, c.document_id, c.text, c.page_hint,
                   vec_distance_cosine(c.embedding, ?) AS distance
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            {where_clause}
            ORDER BY distance
            LIMIT ?
        """
        try:
            with self._query_lock:
                rows = self._conn.execute(
                    sql, [query_blob] + params + [k]
                ).fetchall()
        except sqlite3.Error as exc:
            raise StoreError("vector_search query failed") from exc
        return [
            ChunkHit(
                chunk_id=row["id"],
                document_id=row["document_id"],
                text=row["text"],
                page_hint=row["page_hint"],
                score=float(row["distance"]),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Keyword search
    # ------------------------------------------------------------------

    def keyword_search(
        self,
        terms: Sequence[str],
        k: int,
        filters: SearchFilters,
    ) -> list[ChunkHit]:
        """FTS5 BM25 search over chunks_fts with the same pre-ranking filters.

        Filters are applied as SQL WHERE on documents *before* the FTS MATCH
        ranking, consistent with vector_search (SPEC §6.2).

        Args:
            terms: One or more search terms.  They are combined with AND via
                the FTS5 MATCH syntax.
            k: Maximum number of results to return.
            filters: Pre-ranking filter; applied as SQL WHERE on documents.

        Returns:
            Up to *k* ChunkHit objects ordered by ascending BM25 rank
            (best match first, i.e. most-negative bm25 value).
            ChunkHit.score is the raw bm25() value (negative; closer to 0 is better).

        Raises:
            StoreError: On SQLite error.
        """
        if not terms:
            return []

        # Build the FTS MATCH expression: each term is quoted and joined with AND.
        # Only the structure (AND, quotes) is interpolated — the terms themselves
        # go through parameter substitution via the MATCH ? binding.
        match_expr = " AND ".join(f'"{_escape_fts_term(t)}"' for t in terms)

        where_clause, params = _build_filters(filters)
        # Prefix WHERE with AND if there are already filter clauses; otherwise
        # start with WHERE.
        if where_clause:
            # where_clause already starts with "WHERE"; append the FTS condition.
            fts_join = where_clause + " AND fts.text MATCH ?"
        else:
            fts_join = "WHERE fts.text MATCH ?"

        sql = f"""
            SELECT c.id, c.document_id, c.text, c.page_hint,
                   bm25(chunks_fts) AS rank
            FROM chunks_fts AS fts
            JOIN chunks c ON c.id = fts.rowid
            JOIN documents d ON d.id = c.document_id
            {fts_join}
            ORDER BY rank
            LIMIT ?
        """
        try:
            with self._query_lock:
                rows = self._conn.execute(
                    sql, params + [match_expr, k]
                ).fetchall()
        except sqlite3.Error as exc:
            raise StoreError("keyword_search query failed") from exc
        return [
            ChunkHit(
                chunk_id=row["id"],
                document_id=row["document_id"],
                text=row["text"],
                page_hint=row["page_hint"],
                score=float(row["rank"]),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Document look-ups
    # ------------------------------------------------------------------

    def get_documents(self, ids: Iterable[int]) -> list[IndexedDocument]:
        """Return IndexedDocument objects for the given document ids.

        Joins the taxonomy table to resolve correspondent and document_type
        display names.  Tag names are resolved by reading the tag_ids JSON
        array and looking each up in taxonomy.

        Args:
            ids: Document ids to fetch.

        Returns:
            One IndexedDocument per id that exists in the index.  Order is
            not guaranteed; missing ids are silently omitted.

        Raises:
            StoreError: On SQLite error.
        """
        document_ids = list(ids)
        if not document_ids:
            return []
        # rationale: IN (...) with dynamic ? count — the only sanctioned
        # dynamic SQL pattern (CODE_GUIDELINES §9.5); only the count of ?
        # characters is interpolated, never any value.
        placeholders = ",".join("?" * len(document_ids))
        sql = f"""
            SELECT
                d.id,
                d.title,
                d.correspondent_id,
                d.document_type_id,
                d.tag_ids,
                d.created,
                corr.name  AS correspondent_name,
                dtype.name AS document_type_name
            FROM documents d
            LEFT JOIN taxonomy corr
                ON corr.kind = 'correspondent' AND corr.id = d.correspondent_id
            LEFT JOIN taxonomy dtype
                ON dtype.kind = 'document_type' AND dtype.id = d.document_type_id
            WHERE d.id IN ({placeholders})
        """
        try:
            with self._query_lock:
                rows = self._conn.execute(sql, document_ids).fetchall()
                # Fetch the full tag taxonomy once to resolve names.
                tag_rows = self._conn.execute(
                    "SELECT id, name FROM taxonomy WHERE kind = 'tag'"
                ).fetchall()
        except sqlite3.Error as exc:
            raise StoreError("get_documents query failed") from exc

        tag_name_by_id: dict[int, str] = {row["id"]: row["name"] for row in tag_rows}

        result: list[IndexedDocument] = []
        for row in rows:
            tag_ids: list[int] = json.loads(row["tag_ids"]) if row["tag_ids"] else []
            tag_names = tuple(
                tag_name_by_id[tid] for tid in tag_ids if tid in tag_name_by_id
            )
            result.append(
                IndexedDocument(
                    id=row["id"],
                    title=row["title"],
                    correspondent=row["correspondent_name"],
                    document_type=row["document_type_name"],
                    tags=tag_names,
                    created=row["created"],
                )
            )
        return result

    def get_chunks(self, ids: Iterable[int]) -> list[ChunkHit]:
        """Return ChunkHit objects for the given chunk ids.

        ChunkHit.score is set to 0.0 (no ranking context available for a
        direct look-up).

        Args:
            ids: Chunk ids (chunks.id) to fetch.

        Returns:
            One ChunkHit per id that exists in the index.

        Raises:
            StoreError: On SQLite error.
        """
        chunk_ids = list(ids)
        if not chunk_ids:
            return []
        # rationale: IN (...) with dynamic ? count — sanctioned pattern (§9.5).
        placeholders = ",".join("?" * len(chunk_ids))
        sql = f"""
            SELECT id, document_id, text, page_hint
            FROM chunks
            WHERE id IN ({placeholders})
        """
        try:
            with self._query_lock:
                rows = self._conn.execute(sql, chunk_ids).fetchall()
        except sqlite3.Error as exc:
            raise StoreError("get_chunks query failed") from exc
        return [
            ChunkHit(
                chunk_id=row["id"],
                document_id=row["document_id"],
                text=row["text"],
                page_hint=row["page_hint"],
                score=0.0,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Facets and stats
    # ------------------------------------------------------------------

    def list_facets(self) -> FacetSet:
        """Return all taxonomy entries grouped by kind, plus the date range.

        Returns:
            FacetSet with tuples of TaxonomyEntry for each kind (correspondent,
            document_type, tag) and the earliest/latest created dates from the
            documents table.

        Raises:
            StoreError: On SQLite error.
        """
        try:
            with self._query_lock:
                tax_rows = self._conn.execute(
                    "SELECT kind, id, name FROM taxonomy ORDER BY kind, name"
                ).fetchall()
                date_row = self._conn.execute(
                    "SELECT MIN(created), MAX(created) FROM documents WHERE created IS NOT NULL"
                ).fetchone()
        except sqlite3.Error as exc:
            raise StoreError("list_facets query failed") from exc

        correspondents: list[TaxonomyEntry] = []
        document_types: list[TaxonomyEntry] = []
        tags: list[TaxonomyEntry] = []

        for row in tax_rows:
            entry = TaxonomyEntry(kind=row["kind"], id=row["id"], name=row["name"])
            if row["kind"] == "correspondent":
                correspondents.append(entry)
            elif row["kind"] == "document_type":
                document_types.append(entry)
            elif row["kind"] == "tag":
                tags.append(entry)

        earliest: str | None = date_row[0] if date_row and date_row[0] else None
        latest: str | None = date_row[1] if date_row and date_row[1] else None

        return FacetSet(
            correspondents=tuple(correspondents),
            document_types=tuple(document_types),
            tags=tuple(tags),
            earliest=earliest,
            latest=latest,
        )

    def get_stats(self) -> IndexStats:
        """Return summary statistics for the search index.

        Returns:
            IndexStats with document count, chunk count, last_reconcile_at
            (from meta), and embedding_model (from meta).

        Raises:
            StoreError: On SQLite error.
        """
        try:
            with self._query_lock:
                doc_count_row = self._conn.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()
                chunk_count_row = self._conn.execute(
                    "SELECT COUNT(*) FROM chunks"
                ).fetchone()
                reconcile_row = self._conn.execute(
                    "SELECT value FROM meta WHERE key = 'last_reconcile_at'"
                ).fetchone()
                model_row = self._conn.execute(
                    "SELECT value FROM meta WHERE key = 'embedding_model'"
                ).fetchone()
        except sqlite3.Error as exc:
            raise StoreError("get_stats query failed") from exc

        return IndexStats(
            document_count=doc_count_row[0],
            chunk_count=chunk_count_row[0],
            last_reconcile_at=reconcile_row[0] if reconcile_row else None,
            embedding_model=model_row[0] if model_row else None,
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def quick_check(self) -> bool:
        """Run PRAGMA quick_check on the database.

        Returns:
            True if the database reports 'ok'; False otherwise.

        Raises:
            StoreError: On SQLite error.
        """
        try:
            with self._query_lock:
                row = self._conn.execute("PRAGMA quick_check").fetchone()
        except sqlite3.Error as exc:
            raise StoreError("quick_check failed") from exc
        return row is not None and row[0] == "ok"

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_filters(filters: SearchFilters) -> tuple[str, list[object]]:
    """Build the SQL WHERE clause and parameter list for *filters*.

    Returns a tuple of (where_clause_string, params_list).  If no filters are
    active the where_clause is an empty string.  The WHERE keyword is included
    when at least one clause is present.

    Filter semantics:
    - ``date_from`` / ``date_to``: inclusive range on ``d.created`` using
      lexicographic ISO-8601 string comparison (normalised dates sort correctly).
    - ``correspondent_id``: equality on ``d.correspondent_id``.
    - ``document_type_id``: equality on ``d.document_type_id``.
    - ``tag_ids``: each id in the tuple must appear as a value in
      ``d.tag_ids``, which is stored as a JSON array.  The membership test
      uses ``json_each(d.tag_ids)`` which requires valid JSON — the writer
      serialises tag_ids with ``json.dumps(list(meta.tag_ids))`` (see
      store/writer.py:upsert_document), so all stored values are valid JSON
      arrays and ``json_each`` works correctly.
    """
    clauses: list[str] = []
    params: list[object] = []

    if filters.date_from is not None:
        clauses.append("d.created >= ?")
        params.append(filters.date_from)

    if filters.date_to is not None:
        clauses.append("d.created <= ?")
        params.append(filters.date_to)

    if filters.correspondent_id is not None:
        clauses.append("d.correspondent_id = ?")
        params.append(filters.correspondent_id)

    if filters.document_type_id is not None:
        clauses.append("d.document_type_id = ?")
        params.append(filters.document_type_id)

    for tag_id in filters.tag_ids:
        # Each tag_id must appear in the JSON array stored in d.tag_ids.
        # json_each() expands the array into rows; EXISTS ensures the document
        # is only returned if the given id is present.
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(d.tag_ids) WHERE value = ?)"
        )
        params.append(tag_id)

    if not clauses:
        return "", params

    return "WHERE " + " AND ".join(clauses), params


def _escape_fts_term(term: str) -> str:
    """Escape a single FTS5 search term by doubling embedded double-quotes.

    The term is placed between double-quotes in the MATCH expression so that
    FTS5 treats it as a phrase/token rather than a boolean operator.  Any
    literal double-quote inside the term is doubled per the FTS5 spec.
    """
    return term.replace('"', '""')
