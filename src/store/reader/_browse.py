"""The paginated, sorted, filtered document listing for the Library screen."""

from __future__ import annotations

import sqlite3
import threading

from store.migrations import SchemaNotReadyError, StoreError, _is_missing_table_error
from store.models import DocumentBrowseQuery, DocumentPage, DocumentSummary
from store.reader._filters import build_browse_where
from store.reader._lookups import _names_for_tag_ids, _parse_tag_ids, _resolve_tag_names

# A column name cannot be bound as a ``?`` parameter, so the sort key is mapped
# through this whitelist. The date sorts are index-backed; ``title`` is rarely
# used and falls back to a table sort.
_SORT_COLUMNS: dict[str, str] = {
    "created": "d.created",
    "title": "d.title",
    "indexed_at": "d.indexed_at",
}


def _order_by(sort: str, descending: bool) -> str:
    """Return the ``ORDER BY`` body for a browse query.

    ``d.id`` is appended as a tiebreak so equal sort keys (including NULLs) keep
    a stable order across pages.

    Raises:
        ValueError: *sort* is not in :data:`_SORT_COLUMNS`; the HTTP layer
            validates it, so this is a programming error.
    """
    column = _SORT_COLUMNS.get(sort)
    if column is None:
        allowed = ", ".join(sorted(_SORT_COLUMNS))
        raise ValueError(f"unknown sort column {sort!r}; expected one of {allowed}")
    direction = "DESC" if descending else "ASC"
    # The tiebreak follows the primary direction so paging stays monotonic.
    return f"{column} {direction}, d.id {direction}"


def list_documents(
    conn: sqlite3.Connection,
    query_lock: threading.Lock,
    query: DocumentBrowseQuery,
) -> DocumentPage:
    """List documents with pagination, sorting and filtering.

    The count and page queries run under one hold of *query_lock* so the total
    matches the rows returned.

    Raises:
        ValueError: ``query.sort`` is not a recognised sort column.
        SchemaNotReadyError: The index schema is not present.
        StoreError: On any other SQLite error.
    """
    order_by = _order_by(query.sort, query.descending)
    where_clause, params = build_browse_where(query)

    # where_clause and order_by contain only fixed SQL and ``?`` placeholders;
    # every value is bound as a parameter.
    count_sql = (
        "SELECT COUNT(*) "
        "FROM documents d "
        "LEFT JOIN taxonomy corr "
        "    ON corr.kind = 'correspondent' AND corr.id = d.correspondent_id "
        "LEFT JOIN taxonomy dtype "
        "    ON dtype.kind = 'document_type' AND dtype.id = d.document_type_id "
        f"{where_clause}"  # nosec B608 - where_clause is built from a fixed whitelist of SQL keywords + ? placeholders by build_browse_where()
    )
    page_sql = (
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
        f"{where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?"  # nosec B608 - where_clause/order_by are built from whitelists by build_browse_where()/_order_by(); values via ?
    )
    try:
        with query_lock:
            total_row = conn.execute(count_sql, params).fetchone()
            page_rows = conn.execute(
                page_sql, [*params, query.limit, query.offset]
            ).fetchall()
            # Resolve only the tag ids on this page, not the whole taxonomy.
            all_tag_ids: list[int] = []
            per_row_tag_ids: list[list[int]] = []
            for row in page_rows:
                tag_ids = _parse_tag_ids(row["tag_ids"], document_id=row["id"])
                per_row_tag_ids.append(tag_ids)
                all_tag_ids.extend(tag_ids)
            tag_name_by_id = _resolve_tag_names(conn, list(dict.fromkeys(all_tag_ids)))
    except sqlite3.Error as exc:
        if _is_missing_table_error(exc):
            raise SchemaNotReadyError(
                "list_documents query failed: the index schema is not present"
            ) from exc
        raise StoreError("list_documents query failed") from exc

    documents: list[DocumentSummary] = []
    for row, tag_ids in zip(page_rows, per_row_tag_ids):
        tag_names = _names_for_tag_ids(tag_ids, tag_name_by_id)
        documents.append(
            DocumentSummary(
                id=row["id"],
                title=row["title"],
                correspondent=row["correspondent_name"],
                document_type=row["document_type_name"],
                tags=tag_names,
                created=row["created"],
                page_count=row["page_count"],
            )
        )

    return DocumentPage(
        documents=tuple(documents),
        total=total_row[0],
        offset=query.offset,
        limit=query.limit,
    )
