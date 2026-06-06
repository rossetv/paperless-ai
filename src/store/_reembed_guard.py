"""Re-embed cost-guard — make a full-index wipe loud before it happens.

LLM-11 / IDX-04.  A full re-embed (an ``EMBEDDING_MODEL`` mismatch wipe in
``StoreWriter.check_embedding_model`` or an operator ``rebuild_index``) is the
maximum-cost event in the system: the whole library is re-chunked and
re-embedded on the next reconcile.  :func:`log_reembed_projection` emits a
CRITICAL line naming the trigger and the projected scope *before* the wipe, so
a silent or accidental trigger — e.g. an unpinned ``EMBEDDING_MODEL`` changing
under a watchtower auto-update — is loud in the logs.

These helpers are **observability only**: they never gate the wipe.  A read
error while projecting the scope degrades to a CRITICAL log with the scope
marked unknown (``-1``) and the wipe proceeds — the wipe is correct and
necessary; only its loudness is at stake (CODE_GUIDELINES §1.11 fail-loud
applies to the wipe trigger, not the metric).

They live in a sibling module of :mod:`store.writer` (CODE_GUIDELINES §3.1, to
keep ``writer.py`` under the 500-line ceiling) and take the writer's existing
SQLite connection, so SQLite access stays inside the ``store`` package (§8.2).
"""

from __future__ import annotations

import sqlite3

import structlog

log = structlog.get_logger(__name__)


def project_reembed_scope(conn: sqlite3.Connection) -> tuple[int, int]:
    """Return ``(document_count, chunk_count)`` for the re-embed cost log.

    Read through the writer's existing *conn* for the CRITICAL projected-cost
    log emitted before a full-index wipe.  A read error degrades to
    ``(-1, -1)`` so the caller logs the event with the scope marked unknown and
    proceeds with the wipe rather than aborting it.
    """
    try:
        document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    except sqlite3.Error as exc:
        # rationale: the cost projection is observability only — a read failure
        # here must never block a correct, necessary wipe.  Log the scope as
        # unknown (-1) and let the wipe proceed (CODE_GUIDELINES §1.11 fail-loud
        # applies to the wipe trigger, not the metric).
        log.warning("store.reembed_scope_unreadable", error=str(exc))
        return -1, -1
    return document_count, chunk_count


def log_reembed_projection(
    conn: sqlite3.Connection, *, trigger: str, **context: object
) -> None:
    """Emit the CRITICAL projected-cost log before a full-index wipe.

    Reads the scope via :func:`project_reembed_scope` and logs it at CRITICAL.
    This never changes whether or how the wipe happens; it only narrates it
    (LLM-11 / IDX-04).

    Args:
        conn: The writer's SQLite connection (read through, no transaction).
        trigger: Why the wipe is happening — ``"embedding_model_change"`` or
            ``"index_rebuild"``.
        **context: Extra structured fields (e.g. the model names) to attach.
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
