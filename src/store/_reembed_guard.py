"""Log a full re-embed loudly before the index is wiped.

A full re-embed (embedding-model change or ``rebuild_index``) is the most
expensive event in the system. These helpers only log; they never block the wipe.
"""

from __future__ import annotations

import sqlite3

import structlog

log = structlog.get_logger(__name__)


def project_reembed_scope(conn: sqlite3.Connection) -> tuple[int, int]:
    """Return ``(document_count, chunk_count)``, or ``(-1, -1)`` if unreadable."""
    try:
        document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    except sqlite3.Error as exc:
        # The projection is only for the log; a read failure must not block the wipe.
        log.warning("store.reembed_scope_unreadable", error=str(exc))
        return -1, -1
    return document_count, chunk_count


def log_reembed_projection(
    conn: sqlite3.Connection, *, trigger: str, **context: object
) -> None:
    """Emit the CRITICAL projected-cost log before a full-index wipe.

    *trigger* is ``"embedding_model_change"`` or ``"index_rebuild"``; *context*
    adds structured fields such as the model names.
    """
    document_count, chunk_count = project_reembed_scope(conn)
    log.critical(
        "store.full_reembed_projected",
        trigger=trigger,
        document_count=document_count,
        current_chunk_count=chunk_count,
        projected_reembed_chunks=chunk_count,
        advice=(
            "A full re-embed of the entire index is about to begin: every chunk "
            "will be wiped and re-embedded on the next reconcile. If this was not "
            "intended, stop the indexer and pin EMBEDDING_MODEL before it "
            "restarts."
        ),
        **context,
    )
