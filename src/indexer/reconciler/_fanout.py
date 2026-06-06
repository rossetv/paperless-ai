"""The worker-pool fan-out — index a batch of documents concurrently.

A leaf module of the reconciler package: it owns the concurrent dispatch of a
batch of Paperless documents to the per-document worker, isolating each
document's failure (SPEC §5.7).  It is imported *downward* by both
:mod:`._incremental` (the watermark-page and retry batches) and
:mod:`._light_diff` (the steady-state changed set) so neither has to import the
other — this is what breaks the import cycle without injecting a function
pointer (CODE_GUIDELINES §3.3 leaf extraction).

The :class:`~concurrent.futures.ThreadPoolExecutor` is **not** owned here.  It
is constructed once per reconciliation cycle by :func:`._incremental.run_incremental_sync`
and threaded through every batch, so the indexer spins up and tears down one
pool per cycle rather than one per 100-document batch (IDX-09): on a first-run
backfill of N documents that is one pool instead of ``ceil(N/100)``, and the
``thread_name_prefix`` numbering stays continuous across batches in the logs.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

import structlog

from indexer.worker import IndexOutcome

if TYPE_CHECKING:
    from concurrent.futures import ThreadPoolExecutor

    from common.paperless import PaperlessDocument
    from indexer.worker import DocumentIndexer
    from store.models import IndexState

log = structlog.get_logger(__name__)

# Thread-pool name so log correlation and profilers can attribute the work
# (CODE_GUIDELINES §8.6).  Owned here because this module owns the dispatch.
_WORKER_THREAD_PREFIX = "indexer-document"


def _index_documents(
    pool: ThreadPoolExecutor,
    indexer: DocumentIndexer,
    documents: list[PaperlessDocument],
    index_state: dict[int, IndexState],
) -> dict[int, IndexOutcome | None]:
    """Fan *documents* across *pool* and map each id to its outcome.

    Each document is dispatched to :func:`_index_one`, which catches and
    isolates that document's failure.  The pool is the cycle-scoped pool built
    by :func:`._incremental.run_incremental_sync`, named for log correlation
    (CODE_GUIDELINES §8.6), and reused across every batch of the cycle.

    Returns:
        A mapping of document id to its :class:`~indexer.worker.IndexOutcome`,
        or ``None`` for a document whose indexing raised.
    """
    if not documents:
        return {}

    # A partial binds the indexer and index_state; only the per-document arg
    # varies across the map, which keeps the dispatch readable (no lambda
    # closing over loop state — CODE_GUIDELINES §1.1).
    index_one = functools.partial(_index_one, indexer, index_state)
    return dict(pool.map(index_one, documents))


def _index_one(
    indexer: DocumentIndexer,
    index_state: dict[int, IndexState],
    doc: PaperlessDocument,
) -> tuple[int, IndexOutcome | None]:
    """Index one document, isolating any failure (SPEC §5.7).

    Returns ``(document_id, outcome)`` where *outcome* is the worker's
    :class:`~indexer.worker.IndexOutcome` on success, or ``None`` when indexing
    raised — the failure is logged with its traceback and the cycle continues
    with the next document.  The id is returned alongside the outcome so the
    caller can rebuild the failed-document map regardless of worker-pool
    completion order.
    """
    document_id = doc["id"]
    try:
        return document_id, indexer.index_document(doc, index_state.get(document_id))
    except Exception:
        # rationale: per-document worker dispatch — one document's failure is
        # logged and isolated, the batch continues (CODE_GUIDELINES §6.4
        # site 2, SPEC §5.7).  The failure is recorded in the failed-document
        # map and retried out-of-band next cycle.
        log.exception("reconcile.document_failed", document_id=document_id)
        return document_id, None


__all__ = ["IndexOutcome", "_WORKER_THREAD_PREFIX", "_index_documents", "_index_one"]
