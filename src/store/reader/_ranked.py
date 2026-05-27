"""Ranked-retrieval queries for the search index store.

Implements the two ranked-retrieval operations of the read side: exact
brute-force vector KNN (``vector_search``) and FTS5 BM25 keyword search
(``keyword_search``).  Both apply the caller's :class:`~store.models.SearchFilters`
as SQL WHERE clauses on the documents table *before* ranking, so filtered
recall is exact — there is no "k rows ranked, all filtered out" failure
(SPEC §6.2).

Each function takes the connection and the StoreReader's query lock by
argument; :class:`~store.reader.StoreReader` is the facade that owns them.

Allowed deps: sqlite3, sqlite_vec, store.models, store.reader._filters,
    store.migrations.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence

# rationale: sqlite_vec ships no type stubs; untyped import is unavoidable.
import sqlite_vec  # type: ignore[import-untyped]

from store.migrations import StoreError
from store.models import ChunkHit, SearchFilters
from store.reader._filters import build_filters, escape_fts_term

# Dimension consistency: vector_search passes the query blob directly to
# vec_distance_cosine without a per-row dimension check.  This is safe because
# StoreWriter.check_embedding_model() wipes and rebuilds all chunks whenever
# the embedding model or configured dimension changes, so every stored
# embedding is guaranteed to share the same width.  A per-row fallback for
# mismatched dimensions is therefore unnecessary.


def vector_search(
    conn: sqlite3.Connection,
    query_lock: threading.Lock,
    query_embedding: Sequence[float],
    k: int,
    filters: SearchFilters,
) -> list[ChunkHit]:
    """Exact scalar-distance KNN over the SQL-filtered candidate set.

    Applies *filters* as SQL WHERE clauses on *documents* before ranking by
    cosine distance, so filtered recall is exact (SPEC §6.2).

    Args:
        conn: The open index connection.
        query_lock: The StoreReader's lock, held for the duration of the query.
        query_embedding: The float32 query vector (must match stored dimensions).
        k: Maximum number of results to return.
        filters: Pre-ranking filter; applied as SQL WHERE on documents.

    Returns:
        Up to *k* ChunkHit objects ordered by ascending cosine distance
        (nearest first).  ChunkHit.score is the cosine distance.

    Raises:
        StoreError: On SQLite error.
    """
    if k <= 0:
        return []
    query_blob = sqlite_vec.serialize_float32(list(query_embedding))
    where_clause, params = build_filters(filters)
    # rationale: where_clause is composed solely of fixed SQL keywords and
    # ``?`` placeholders by build_filters — no caller value is ever spliced
    # into the string.  Every filter value travels in *params* and is bound by
    # parameter substitution (CODE_GUIDELINES §9.5).
    sql = (
        "SELECT c.id, c.document_id, c.text, c.page_hint, "
        "       vec_distance_cosine(c.embedding, ?) AS distance "
        "FROM chunks c "
        "JOIN documents d ON d.id = c.document_id "
        f"{where_clause} ORDER BY distance LIMIT ?"  # nosec B608 - where_clause is built from a fixed whitelist + ? placeholders by build_filters(); values bound via ?
    )
    try:
        with query_lock:
            rows = conn.execute(sql, [query_blob, *params, k]).fetchall()
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


def keyword_search(
    conn: sqlite3.Connection,
    query_lock: threading.Lock,
    terms: Sequence[str],
    k: int,
    filters: SearchFilters,
) -> list[ChunkHit]:
    """FTS5 BM25 search over chunks_fts with the same pre-ranking filters.

    Filters are applied as SQL WHERE on documents *before* the FTS MATCH
    ranking, consistent with :func:`vector_search` (SPEC §6.2).

    Args:
        conn: The open index connection.
        query_lock: The StoreReader's lock, held for the duration of the query.
        terms: One or more search terms.  They are combined with AND via the
            FTS5 MATCH syntax.
        k: Maximum number of results to return.
        filters: Pre-ranking filter; applied as SQL WHERE on documents.

    Returns:
        Up to *k* ChunkHit objects ordered by ascending BM25 rank (best match
        first, i.e. most-negative bm25 value).  ChunkHit.score is the raw
        bm25() value (negative; closer to 0 is better).

    Raises:
        StoreError: On SQLite error.
    """
    if not terms or k <= 0:
        return []

    # Build the FTS MATCH expression: each term is quoted and joined with AND.
    # Only the structure (AND, quotes) is assembled here — the term text itself
    # goes through parameter substitution via the MATCH ? binding below.
    match_expr = " AND ".join(f'"{escape_fts_term(term)}"' for term in terms)

    where_clause, params = build_filters(filters)
    # Append the FTS condition: when build_filters produced clauses the string
    # already opens with WHERE, so AND extends it; otherwise WHERE starts it.
    if where_clause:
        fts_join = where_clause + " AND fts.text MATCH ?"
    else:
        fts_join = "WHERE fts.text MATCH ?"

    # rationale: fts_join is built only from fixed SQL keywords and ``?``
    # placeholders (build_filters' output plus the literal MATCH clause) — no
    # caller value is spliced into the string.  The terms and every filter
    # value are bound by parameter substitution (CODE_GUIDELINES §9.5).
    sql = (
        "SELECT c.id, c.document_id, c.text, c.page_hint, "
        "       bm25(chunks_fts) AS rank "
        "FROM chunks_fts AS fts "
        "JOIN chunks c ON c.id = fts.rowid "
        "JOIN documents d ON d.id = c.document_id "
        f"{fts_join} ORDER BY rank LIMIT ?"  # nosec B608 - fts_join is build_filters() output + literal "AND fts.text MATCH ?"; values bound via ?
    )
    try:
        with query_lock:
            rows = conn.execute(sql, [*params, match_expr, k]).fetchall()
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
