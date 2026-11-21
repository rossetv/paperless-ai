"""Non-ranked reads: look-ups by id, taxonomy, facets, stats, integrity check."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable

import structlog

from store._sql import placeholders

# A fresh, empty index raises "no such table", mapped to SchemaNotReadyError.
from store.migrations import (
    SchemaNotReadyError,
    StoreError,
    _is_missing_table_error,
)
from store.models import (
    ChunkHit,
    DocumentSummary,
    FailedDocument,
    FacetSet,
    FilterCatalog,
    FilterFacet,
    IndexedDocument,
    IndexStats,
    TaxonomyEntry,
)

log = structlog.get_logger(__name__)


def _names_for_tag_ids(
    tag_ids: list[int], tag_name_by_id: dict[int, str]
) -> tuple[str, ...]:
    """Resolve *tag_ids* to names in order, dropping ids with no entry.

    A tag deleted from Paperless after indexing simply disappears.
    """
    return tuple(
        tag_name_by_id[tag_id] for tag_id in tag_ids if tag_id in tag_name_by_id
    )


def get_documents(
    conn: sqlite3.Connection,
    query_lock: threading.Lock,
    ids: Iterable[int],
) -> list[IndexedDocument]:
    """Return an IndexedDocument per existing id; order is not guaranteed."""
    document_ids = list(ids)
    if not document_ids:
        return []
    sql = (
        "SELECT "
        "    d.id, "
        "    d.title, "
        "    d.correspondent_id, "
        "    d.document_type_id, "
        "    d.tag_ids, "
        "    d.created, "
        "    corr.name  AS correspondent_name, "
        "    dtype.name AS document_type_name "
        "FROM documents d "
        "LEFT JOIN taxonomy corr "
        "    ON corr.kind = 'correspondent' AND corr.id = d.correspondent_id "
        "LEFT JOIN taxonomy dtype "
        "    ON dtype.kind = 'document_type' AND dtype.id = d.document_type_id "
        f"WHERE d.id IN ({placeholders(len(document_ids))})"  # nosec B608 - placeholders() emits `?,?,?` from an int; ids bound via ?
    )
    try:
        with query_lock:
            rows = conn.execute(sql, document_ids).fetchall()
            # Resolve only the tag ids on these documents, not the whole taxonomy.
            all_tag_ids: list[int] = []
            per_row_tag_ids: list[list[int]] = []
            for row in rows:
                tag_ids = _parse_tag_ids(row["tag_ids"], document_id=row["id"])
                per_row_tag_ids.append(tag_ids)
                all_tag_ids.extend(tag_ids)
            tag_name_by_id = _resolve_tag_names(conn, list(dict.fromkeys(all_tag_ids)))
    except sqlite3.Error as exc:
        raise StoreError("get_documents query failed") from exc

    documents: list[IndexedDocument] = []
    for row, tag_ids in zip(rows, per_row_tag_ids):
        tag_names = _names_for_tag_ids(tag_ids, tag_name_by_id)
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
    """Return a ChunkHit per existing chunk id, with ``score`` 0.0 (unranked)."""
    chunk_ids = list(ids)
    if not chunk_ids:
        return []
    sql = (
        "SELECT id, document_id, text, page_hint "
        "FROM chunks "
        f"WHERE id IN ({placeholders(len(chunk_ids))})"  # nosec B608 - placeholders() emits `?,?,?` from an int; ids bound via ?
    )
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
    """Return every taxonomy entry of the given *kind*, ordered by name."""
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

    Raises:
        SchemaNotReadyError: The schema is not present (an empty file, or mid
            rebuild), so the server can answer 503 rather than 500.
        StoreError: On any other SQLite error.
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
        if _is_missing_table_error(exc):
            raise SchemaNotReadyError(
                "list_facets query failed: the index schema is not present"
            ) from exc
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


def list_filters_with_counts(
    conn: sqlite3.Connection, query_lock: threading.Lock
) -> FilterCatalog:
    """Return every taxonomy entry with its document count, plus the date range.

    Lets an MCP caller see which filter ids are worth using.

    Raises:
        SchemaNotReadyError: The index schema is not present.
        StoreError: On any other SQLite error.
    """
    try:
        with query_lock:
            tax_rows = conn.execute(
                "SELECT kind, id, name FROM taxonomy ORDER BY kind, name"
            ).fetchall()
            corr_counts = dict(
                conn.execute(
                    "SELECT correspondent_id, COUNT(*) FROM documents "
                    "WHERE correspondent_id IS NOT NULL GROUP BY correspondent_id"
                ).fetchall()
            )
            type_counts = dict(
                conn.execute(
                    "SELECT document_type_id, COUNT(*) FROM documents "
                    "WHERE document_type_id IS NOT NULL GROUP BY document_type_id"
                ).fetchall()
            )
            tag_counts = dict(
                conn.execute(
                    "SELECT je.value, COUNT(*) FROM documents d, "
                    "json_each(d.tag_ids) je GROUP BY je.value"
                ).fetchall()
            )
            date_row = conn.execute(
                "SELECT MIN(created), MAX(created) FROM documents "
                "WHERE created IS NOT NULL"
            ).fetchone()
    except sqlite3.Error as exc:
        if _is_missing_table_error(exc):
            raise SchemaNotReadyError(
                "list_filters_with_counts query failed: the index schema is not present"
            ) from exc
        raise StoreError("list_filters_with_counts query failed") from exc

    counts_by_kind = {
        "correspondent": corr_counts,
        "document_type": type_counts,
        "tag": tag_counts,
    }
    buckets: dict[str, list[FilterFacet]] = {
        "correspondent": [],
        "document_type": [],
        "tag": [],
    }
    for row in tax_rows:
        kind = row["kind"]
        if kind in buckets:
            buckets[kind].append(
                FilterFacet(
                    id=row["id"],
                    name=row["name"],
                    count=int(counts_by_kind[kind].get(row["id"], 0)),
                )
            )

    earliest: str | None = date_row[0] if date_row and date_row[0] else None
    latest: str | None = date_row[1] if date_row and date_row[1] else None

    return FilterCatalog(
        correspondents=tuple(buckets["correspondent"]),
        document_types=tuple(buckets["document_type"]),
        tags=tuple(buckets["tag"]),
        earliest=earliest,
        latest=latest,
    )


def get_stats(conn: sqlite3.Connection, query_lock: threading.Lock) -> IndexStats:
    """Return summary statistics for the search index.

    Raises:
        SchemaNotReadyError: The indexer has not created the schema yet, so
            healthz can report "index not ready".
        StoreError: On any other SQLite error.
    """
    try:
        with query_lock:
            doc_count_row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
            chunk_count_row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
            # Served by idx_documents_indexed_at, so this is an index scan.
            latest_indexed_row = conn.execute(
                "SELECT MAX(indexed_at) FROM documents"
            ).fetchone()
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
        latest_indexed_at=latest_indexed_row[0] if latest_indexed_row else None,
    )


# JSON object of str(doc_id) -> consecutive failure count, written by
# indexer.reconciler._failed_documents.
_FAILED_DOCUMENTS_META_KEY = "failed_documents"


def get_failed_documents(
    conn: sqlite3.Connection, query_lock: threading.Lock
) -> list[FailedDocument]:
    """Return the documents the indexer has failed to index, ordered by id.

    A document that was never stored is listed with a ``None`` title. A corrupt
    meta value yields an empty list rather than breaking the dashboard.

    Raises:
        SchemaNotReadyError: The index schema is not present.
        StoreError: On any other SQLite error.
    """
    try:
        with query_lock:
            meta_row = conn.execute(
                "SELECT value FROM meta WHERE key = ?",
                (_FAILED_DOCUMENTS_META_KEY,),
            ).fetchone()
            failure_counts = _parse_failed_documents(meta_row[0] if meta_row else None)
            if not failure_counts:
                return []
            titles = _fetch_titles(conn, list(failure_counts))
    except sqlite3.Error as exc:
        if _is_missing_table_error(exc):
            raise SchemaNotReadyError(
                "get_failed_documents query failed: schema not present"
            ) from exc
        raise StoreError("get_failed_documents query failed") from exc

    return [
        FailedDocument(
            document_id=doc_id,
            title=titles.get(doc_id),
            failure_count=count,
        )
        for doc_id, count in sorted(failure_counts.items())
    ]


def _parse_failed_documents(raw: str | None) -> dict[int, int]:
    """Decode the failed_documents meta JSON; malformed input yields ``{}``."""
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            return {}
        return {int(key): int(value) for key, value in decoded.items()}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def _fetch_titles(conn: sqlite3.Connection, ids: list[int]) -> dict[int, str | None]:
    """Return a doc-id -> title map; ids with no ``documents`` row are absent."""
    if not ids:
        return {}
    rows = conn.execute(
        f"SELECT id, title FROM documents WHERE id IN ({placeholders(len(ids))})",  # nosec B608 - placeholders() emits `?,?,?` from an int; ids bound via ?
        ids,
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def quick_check(conn: sqlite3.Connection, query_lock: threading.Lock) -> bool:
    """Run ``PRAGMA quick_check``; return whether the database reports ``'ok'``."""
    try:
        with query_lock:
            row = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as exc:
        raise StoreError("quick_check failed") from exc
    return row is not None and row[0] == "ok"


def _parse_tag_ids(raw_tag_ids: str | None, *, document_id: int) -> list[int]:
    """Parse the documents.tag_ids JSON array; NULL or corrupt yields no tags."""
    if not raw_tag_ids:
        return []
    try:
        return json.loads(raw_tag_ids)
    except json.JSONDecodeError:
        log.warning(
            "get_document_summary.tag_ids_parse_error",
            document_id=document_id,
            raw=raw_tag_ids[:80],
        )
        return []


def _resolve_tag_names(conn: sqlite3.Connection, tag_ids: list[int]) -> dict[int, str]:
    """Return a {tag id: name} map for exactly *tag_ids*.

    Scoping by id rather than loading every tag is ~90x faster for 3 tags
    against a 2,000-tag taxonomy.
    """
    if not tag_ids:
        return {}
    marks = placeholders(len(tag_ids))
    rows = conn.execute(
        f"SELECT id, name FROM taxonomy WHERE kind = 'tag' AND id IN ({marks})",  # nosec B608 - marks is `?,?,?` from placeholders(); ids bound via ?
        tag_ids,
    ).fetchall()
    return {r["id"]: r["name"] for r in rows}


def get_document_summary(
    conn: sqlite3.Connection,
    query_lock: threading.Lock,
    document_id: int,
) -> DocumentSummary | None:
    """Return the DocumentSummary for one document id, or None if absent."""
    sql = (
        "SELECT "
        "    d.id, "
        "    d.title, "
        "    d.tag_ids, "
        "    d.created, "
        "    d.page_count, "
        "    corr.name  AS correspondent_name, "
        "    dtype.name AS document_type_name "
        "FROM documents d "
        "LEFT JOIN taxonomy corr "
        "    ON corr.kind = 'correspondent' AND corr.id = d.correspondent_id "
        "LEFT JOIN taxonomy dtype "
        "    ON dtype.kind = 'document_type' AND dtype.id = d.document_type_id "
        "WHERE d.id = ?"
    )
    try:
        with query_lock:
            row = conn.execute(sql, (document_id,)).fetchone()
            if row is None:
                return None
            tag_ids = _parse_tag_ids(row["tag_ids"], document_id=row["id"])
            tag_name_by_id = _resolve_tag_names(conn, tag_ids)
    except sqlite3.Error as exc:
        raise StoreError("get_document_summary query failed") from exc

    tag_names = _names_for_tag_ids(tag_ids, tag_name_by_id)
    return DocumentSummary(
        id=row["id"],
        title=row["title"],
        correspondent=row["correspondent_name"],
        document_type=row["document_type_name"],
        tags=tag_names,
        created=row["created"],
        page_count=row["page_count"],
    )
