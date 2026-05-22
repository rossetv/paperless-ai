"""Look-up and introspection queries for the search index store.

Implements the non-ranked read operations: document and chunk look-up by id,
taxonomy reads, facet aggregation, index statistics, and the integrity check.
None of these rank — they resolve known ids or summarise the index.

Each function takes the connection and the StoreReader's query lock by
argument; :class:`~store.reader.StoreReader` is the facade that owns them.

Allowed deps: sqlite3, json, store.models, store._sql, store.migrations.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable

from store._sql import placeholders
from store.migrations import SchemaNotReadyError, StoreError
from store.models import (
    ChunkHit,
    FacetSet,
    IndexedDocument,
    IndexStats,
    TaxonomyEntry,
)

# Substring SQLite uses in the ``OperationalError`` message when a queried
# table does not exist.  A fresh, schema-less index database (auto-created
# empty by ``sqlite3.connect``) produces this; the store maps it to the typed
# ``SchemaNotReadyError`` so callers never string-match ``sqlite3`` internals.
_NO_SUCH_TABLE_MARKER = "no such table"


def _is_missing_table_error(exc: sqlite3.Error) -> bool:
    """Return whether *exc* is a SQLite "no such table" operational error."""
    return (
        isinstance(exc, sqlite3.OperationalError)
        and _NO_SUCH_TABLE_MARKER in str(exc).lower()
    )


def get_documents(
    conn: sqlite3.Connection,
    query_lock: threading.Lock,
    ids: Iterable[int],
) -> list[IndexedDocument]:
    """Return IndexedDocument objects for the given document ids.

    Joins the taxonomy table to resolve correspondent and document_type
    display names.  Tag names are resolved by reading the tag_ids JSON array
    and looking each id up in taxonomy.

    Args:
        conn: The open index connection.
        query_lock: The StoreReader's lock, held for the duration of the query.
        ids: Document ids to fetch.

    Returns:
        One IndexedDocument per id that exists in the index.  Order is not
        guaranteed; missing ids are silently omitted.

    Raises:
        StoreError: On SQLite error.
    """
    document_ids = list(ids)
    if not document_ids:
        return []
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
        WHERE d.id IN ({placeholders(len(document_ids))})
    """
    try:
        with query_lock:
            rows = conn.execute(sql, document_ids).fetchall()
            # Fetch the full tag taxonomy once to resolve names.
            tag_rows = conn.execute(
                "SELECT id, name FROM taxonomy WHERE kind = 'tag'"
            ).fetchall()
    except sqlite3.Error as exc:
        raise StoreError("get_documents query failed") from exc

    tag_name_by_id: dict[int, str] = {row["id"]: row["name"] for row in tag_rows}

    documents: list[IndexedDocument] = []
    for row in rows:
        tag_ids: list[int] = json.loads(row["tag_ids"]) if row["tag_ids"] else []
        tag_names = tuple(
            tag_name_by_id[tag_id] for tag_id in tag_ids if tag_id in tag_name_by_id
        )
        documents.append(
            IndexedDocument(
                id=row["id"],
                title=row["title"],
                correspondent=row["correspondent_name"],
                document_type=row["document_type_name"],
                tags=tag_names,
                created=row["created"],
            )
        )
    return documents


def get_chunks(
    conn: sqlite3.Connection,
    query_lock: threading.Lock,
    ids: Iterable[int],
) -> list[ChunkHit]:
    """Return ChunkHit objects for the given chunk ids.

    ChunkHit.score is set to 0.0 — a direct look-up carries no ranking context.

    Args:
        conn: The open index connection.
        query_lock: The StoreReader's lock, held for the duration of the query.
        ids: Chunk ids (chunks.id) to fetch.

    Returns:
        One ChunkHit per id that exists in the index.

    Raises:
        StoreError: On SQLite error.
    """
    chunk_ids = list(ids)
    if not chunk_ids:
        return []
    sql = f"""
        SELECT id, document_id, text, page_hint
        FROM chunks
        WHERE id IN ({placeholders(len(chunk_ids))})
    """
    try:
        with query_lock:
            rows = conn.execute(sql, chunk_ids).fetchall()
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


def get_taxonomy(
    conn: sqlite3.Connection,
    query_lock: threading.Lock,
    kind: str,
) -> list[TaxonomyEntry]:
    """Return every taxonomy entry of the given *kind*, ordered by name.

    Args:
        conn: The open index connection.
        query_lock: The StoreReader's lock, held for the duration of the query.
        kind: One of ``'correspondent'``, ``'document_type'``, or ``'tag'``.

    Returns:
        The matching TaxonomyEntry rows; an empty list when none exist.

    Raises:
        StoreError: On SQLite error.
    """
    try:
        with query_lock:
            rows = conn.execute(
                "SELECT kind, id, name FROM taxonomy WHERE kind = ? ORDER BY name",
                (kind,),
            ).fetchall()
    except sqlite3.Error as exc:
        raise StoreError(f"get_taxonomy query failed for kind {kind!r}") from exc
    return [
        TaxonomyEntry(kind=row["kind"], id=row["id"], name=row["name"]) for row in rows
    ]


def list_facets(conn: sqlite3.Connection, query_lock: threading.Lock) -> FacetSet:
    """Return all taxonomy entries grouped by kind, plus the date range.

    Returns:
        FacetSet with tuples of TaxonomyEntry for each kind (correspondent,
        document_type, tag) and the earliest/latest created dates from the
        documents table.

    Raises:
        StoreError: On SQLite error.
    """
    try:
        with query_lock:
            tax_rows = conn.execute(
                "SELECT kind, id, name FROM taxonomy ORDER BY kind, name"
            ).fetchall()
            date_row = conn.execute(
                "SELECT MIN(created), MAX(created) FROM documents "
                "WHERE created IS NOT NULL"
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


def get_stats(conn: sqlite3.Connection, query_lock: threading.Lock) -> IndexStats:
    """Return summary statistics for the search index.

    Returns:
        IndexStats with document count, chunk count, last_reconcile_at (from
        meta), and embedding_model (from meta).

    Raises:
        SchemaNotReadyError: The database has no schema yet (a present-but-empty
            file the indexer has not initialised).  Distinguishing this from a
            generic failure lets the search server's healthz handler report
            "index not ready" without inspecting ``sqlite3`` internals.
        StoreError: On any other SQLite error.
    """
    try:
        with query_lock:
            doc_count_row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
            chunk_count_row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
            reconcile_row = conn.execute(
                "SELECT value FROM meta WHERE key = 'last_reconcile_at'"
            ).fetchone()
            model_row = conn.execute(
                "SELECT value FROM meta WHERE key = 'embedding_model'"
            ).fetchone()
    except sqlite3.Error as exc:
        if _is_missing_table_error(exc):
            raise SchemaNotReadyError(
                "get_stats query failed: the index schema is not present"
            ) from exc
        raise StoreError("get_stats query failed") from exc

    return IndexStats(
        document_count=doc_count_row[0],
        chunk_count=chunk_count_row[0],
        last_reconcile_at=reconcile_row[0] if reconcile_row else None,
        embedding_model=model_row[0] if model_row else None,
    )


def quick_check(conn: sqlite3.Connection, query_lock: threading.Lock) -> bool:
    """Run ``PRAGMA quick_check`` on the database.

    Returns:
        True if the database reports ``'ok'``; False otherwise.

    Raises:
        StoreError: On SQLite error.
    """
    try:
        with query_lock:
            row = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as exc:
        raise StoreError("quick_check failed") from exc
    return row is not None and row[0] == "ok"
