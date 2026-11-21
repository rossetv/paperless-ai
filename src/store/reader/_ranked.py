"""Ranked retrieval: exact brute-force vector KNN and FTS5 BM25 keyword search.

Filters are applied in SQL *before* ranking, so filtered recall is exact: there
is no "k rows ranked, all filtered out" failure.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence

# sqlite_vec ships no type stubs.
import sqlite_vec  # type: ignore[import-untyped]

from store.migrations import StoreError
from store.models import ChunkHit, SearchFilters
from store.reader._filters import build_filters, escape_fts_term

# No per-row dimension check is needed: StoreWriter.check_embedding_model()
# wipes every chunk when the model or dimensions change, so all stored
# embeddings share one width.


def vector_search(
    conn: sqlite3.Connection,
    query_lock: threading.Lock,
    query_embedding: Sequence[float],
    k: int,
    filters: SearchFilters,
) -> list[ChunkHit]:
    """Exact KNN over the SQL-filtered candidate set, nearest first.

    ``ChunkHit.score`` is the cosine distance.
    """
    if k <= 0:
        return []
    query_blob = sqlite_vec.serialize_float32(list(query_embedding))
    where_clause, params = build_filters(filters)
    # where_clause holds only fixed SQL and ``?`` placeholders.
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
    """FTS5 BM25 search over chunks_fts, *terms* AND-combined, best match first.

    ``ChunkHit.score`` is the raw ``bm25()`` value: negative, and the most
    negative is the best match.
    """
    if not terms or k <= 0:
        return []

    # The whole MATCH expression is bound as one parameter.
    match_expr = " AND ".join(f'"{escape_fts_term(term)}"' for term in terms)

    where_clause, params = build_filters(filters)
    if where_clause:
        fts_join = where_clause + " AND fts.text MATCH ?"
    else:
        fts_join = "WHERE fts.text MATCH ?"

    # fts_join holds only fixed SQL and ``?`` placeholders.
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


def keyword_document_search(
    conn: sqlite3.Connection,
    query_lock: threading.Lock,
    terms: Sequence[str],
    filters: SearchFilters,
    limit: int,
    offset: int,
) -> tuple[list[tuple[int, str, float]], int]:
    """Like :func:`keyword_search`, but one row per document: its best chunk.

    Returns ``(rows, total)``: rows of ``(document_id, best_chunk_text,
    best_rank)``, best first, and the distinct matching-document count ignoring
    pagination.
    """
    if not terms or limit <= 0:
        return [], 0

    match_expr = " AND ".join(f'"{escape_fts_term(term)}"' for term in terms)
    where_clause, params = build_filters(filters)
    if where_clause:
        fts_join = where_clause + " AND fts.text MATCH ?"
    else:
        fts_join = "WHERE fts.text MATCH ?"

    # fts_join holds only fixed SQL and ``?`` placeholders.
    # Two CTEs: compute bm25 once per matching chunk, then keep each document's
    # best (lowest-rank) chunk via a window function before paginating.
    page_sql = (
        "WITH ranked AS ("
        "  SELECT c.document_id AS doc_id, c.text AS text, "
        "         bm25(chunks_fts) AS rank "
        "  FROM chunks_fts AS fts "
        "  JOIN chunks c ON c.id = fts.rowid "
        "  JOIN documents d ON d.id = c.document_id "
        f"  {fts_join}"  # nosec B608 - fts_join is build_filters()+literal MATCH; values via ?
        "), best AS ("
        "  SELECT doc_id, text, rank, "
        "         ROW_NUMBER() OVER (PARTITION BY doc_id ORDER BY rank) AS rn "
        "  FROM ranked"
        ") "
        "SELECT doc_id, text, rank FROM best WHERE rn = 1 "
        "ORDER BY rank LIMIT ? OFFSET ?"
    )
    count_sql = (
        "SELECT COUNT(DISTINCT c.document_id) "
        "FROM chunks_fts AS fts "
        "JOIN chunks c ON c.id = fts.rowid "
        "JOIN documents d ON d.id = c.document_id "
        f"{fts_join}"  # nosec B608 - same provenance as page_sql's fts_join
    )
    try:
        with query_lock:
            total = conn.execute(count_sql, [*params, match_expr]).fetchone()[0]
            rows = conn.execute(
                page_sql, [*params, match_expr, limit, offset]
            ).fetchall()
    except sqlite3.Error as exc:
        raise StoreError("keyword_document_search query failed") from exc

    return [(row["doc_id"], row["text"], float(row["rank"])) for row in rows], int(
        total
    )
