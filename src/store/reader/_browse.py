"""The Library document-browse query for the search index store.

Implements :func:`list_documents` — a paginated, sorted, filtered listing of
the ``documents`` table for the Library screen (web-redesign §5).  It is the
browse counterpart of the ranked-retrieval queries in
:mod:`store.reader._ranked` and the id look-ups in
:mod:`store.reader._lookups`; the :class:`~store.reader.StoreReader` facade
owns it and delegates each call.

The function takes the connection and the StoreReader's query lock by
argument and holds the lock across both the count query and the page query
so the reported total is consistent with the returned rows.

Allowed deps: sqlite3, json, store.models, store.reader._filters,
    store.migrations.
"""

from __future__ import annotations

import json
import sqlite3
import threading

import structlog

from store.migrations import StoreError
from store.models import DocumentBrowseQuery, DocumentPage, DocumentSummary
from store.reader._filters import build_browse_where

log = structlog.get_logger(__name__)

# The browse sort whitelist.  ``sort`` is a SQL identifier, not a value, so it
# cannot be bound as a ``?`` parameter — it is mapped here through a fixed
# dict to a fixed column expression.  Only these expressions ever reach the
# SQL string; an unknown key raises ValueError before any query runs
# (CODE_GUIDELINES §9.5).  Every expression is a documents-table column the
# schema indexes (idx_documents_created, etc.) where one exists.
_SORT_COLUMNS: dict[str, str] = {
    "created": "d.created",
    "title": "d.title",
    "indexed_at": "d.indexed_at",
}


def _order_by(sort: str, descending: bool) -> str:
    """Return the validated ``ORDER BY`` body for a browse query.

    *sort* is mapped through :data:`_SORT_COLUMNS` — an unknown value is a
    programming error (the HTTP layer validates the query parameter) and
    raises :class:`ValueError`.  The direction is one of two fixed literals.
    ``d.id`` is always appended as a stable tiebreak so rows with an equal
    sort key (including two NULLs) keep a deterministic order across pages.

    Args:
        sort: The requested sort key; must be a key of :data:`_SORT_COLUMNS`.
        descending: True for ``DESC``, False for ``ASC``.

    Returns:
        The text after ``ORDER BY`` — fixed SQL only, no caller value.

    Raises:
        ValueError: *sort* is not a recognised sort column.
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
    """List documents from the index with pagination, sorting and filtering.

    Joins the ``taxonomy`` table to resolve correspondent and document-type
    display names; tag names are resolved by reading each document's
    ``tag_ids`` JSON array against the full tag taxonomy.  The reported
    :attr:`~store.models.DocumentPage.total` is the count of documents
    matching the query's filters ignoring pagination — the count query and
    the page query run under one held lock so the two are consistent.

    Args:
        conn: The open index connection.
        query_lock: The StoreReader's lock, held for the duration of the
            count-and-page query pair.
        query: The browse parameters — filters, sort, and pagination.

    Returns:
        A :class:`~store.models.DocumentPage` — the page rows in sort order
        plus the total match count and the echoed offset and limit.

    Raises:
        ValueError: ``query.sort`` is not a recognised sort column.
        StoreError: On SQLite error.
    """
    # _order_by validates the sort before any SQL runs — a bad sort is a
    # programming error, surfaced as ValueError, never a StoreError.
    order_by = _order_by(query.sort, query.descending)
    where_clause, params = build_browse_where(query)

    # rationale: where_clause and order_by are composed solely of fixed SQL
    # keywords, the _SORT_COLUMNS whitelist, and ``?`` placeholders — no
    # caller value is ever spliced into either string.  Every filter value
    # and the offset/limit travel in the parameter lists and are bound by
    # substitution (CODE_GUIDELINES §9.5).
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
            # Resolve tag names once for the whole page.
            tag_rows = conn.execute(
                "SELECT id, name FROM taxonomy WHERE kind = 'tag'"
            ).fetchall()
    except sqlite3.Error as exc:
        raise StoreError("list_documents query failed") from exc

    tag_name_by_id: dict[int, str] = {row["id"]: row["name"] for row in tag_rows}

    documents: list[DocumentSummary] = []
    for row in page_rows:
        raw_tag_ids = row["tag_ids"]
        if raw_tag_ids:
            try:
                tag_ids: list[int] = json.loads(raw_tag_ids)
            except json.JSONDecodeError:
                log.warning(
                    "browse.tag_ids_parse_error",
                    document_id=row["id"],
                    raw=raw_tag_ids[:80],
                )
                tag_ids = []
        else:
            tag_ids = []
        tag_names = tuple(
            tag_name_by_id[tag_id] for tag_id in tag_ids if tag_id in tag_name_by_id
        )
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
