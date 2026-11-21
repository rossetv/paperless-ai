"""Index a batch of documents concurrently, isolating each document's failure.

Shared by ``_incremental`` and ``_light_diff`` so neither imports the other. The
thread pool is built once per cycle by ``run_incremental_sync``, not per batch.
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

# Thread-name prefix so logs and profilers can attribute the work.
_WORKER_THREAD_PREFIX = "indexer-document"


def _index_documents(
    pool: ThreadPoolExecutor,
    indexer: DocumentIndexer,
    documents: list[PaperlessDocument],
    index_state: dict[int, IndexState],
) -> dict[int, IndexOutcome | None]:
    """Fan *documents* across *pool* and map each id to its outcome.

    The outcome is ``None`` for a document whose indexing raised.
    """
    if not documents:
        return {}

    index_one = functools.partial(_index_one, indexer, index_state)
    return dict(pool.map(index_one, documents))


def _index_one(
    indexer: DocumentIndexer,
    index_state: dict[int, IndexState],
    doc: PaperlessDocument,
) -> tuple[int, IndexOutcome | None]:
    """Index one document, returning ``(document_id, outcome)``.

    *outcome* is ``None`` when indexing raised; the failure is logged.
    """
    document_id = doc["id"]
    try:
        return document_id, indexer.index_document(doc, index_state.get(document_id))
    except Exception:
        # One document's failure must not abort the batch; it is retried next cycle.
        log.exception("reconcile.document_failed", document_id=document_id)
        return document_id, None
