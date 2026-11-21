"""Bounded failed-document retry and dead-lettering for the reconciler.

Failed documents are kept in store meta as ``str(doc_id) -> consecutive
failures`` and retried out-of-band each cycle, so one bad document can neither
stall the watermark nor be retried forever.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import structlog

from common.paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessDocument

if TYPE_CHECKING:
    from common.paperless import PaperlessClient
    from indexer.worker import IndexOutcome
    from store.writer import StoreWriter

log = structlog.get_logger(__name__)

# After this many consecutive failures a document is dead-lettered: dropped
# from the retry map and retried only when its Paperless content next changes.
MAX_CONSECUTIVE_DOCUMENT_FAILURES = 5

_FAILED_DOCUMENTS_META_KEY = "failed_documents"


def read_failed_documents(store_writer: StoreWriter) -> dict[int, int]:
    """Read the persisted failed-document map from store meta.

    A missing or corrupt value yields an empty map rather than crashing the
    cycle; it self-heals as documents fail or succeed again.
    """
    raw = store_writer.read_meta(_FAILED_DOCUMENTS_META_KEY)
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
        return {int(key): int(value) for key, value in decoded.items()}
    except (ValueError, AttributeError, TypeError):
        log.warning("reconcile.failed_documents_unreadable", raw_value=raw)
        return {}


def fetch_retry_documents(
    paperless: PaperlessClient,
    failed_map: dict[int, int],
    page_ids: set[int],
) -> list[PaperlessDocument]:
    """Fetch every failed document not already in the watermark page *page_ids*.

    Ids deleted from Paperless are removed from *failed_map* in place; the
    deletion sweep prunes them from the store. A transport error on one id
    leaves its count unchanged and it is retried next cycle.
    """
    uncovered = sorted(set(failed_map) - page_ids)
    retry_documents: list[PaperlessDocument] = []
    for document_id in uncovered:
        try:
            if not paperless.document_exists(document_id):
                del failed_map[document_id]
                log.info("reconcile.failed_document_gone", document_id=document_id)
                continue
            retry_documents.append(
                cast("PaperlessDocument", paperless.get_document(document_id))
            )
        except PAPERLESS_CALL_EXCEPTIONS:
            log.exception(
                "reconcile.failed_document_refetch_failed",
                document_id=document_id,
            )
    return retry_documents


def update_failed_documents(
    store_writer: StoreWriter,
    failed_map: dict[int, int],
    outcomes: dict[int, IndexOutcome | None],
) -> int:
    """Update *failed_map* in place from a cycle's outcomes and persist it.

    A success clears the id; a failure (``None``) increments its count and
    dead-letters it at :data:`MAX_CONSECUTIVE_DOCUMENT_FAILURES`. Ids the cycle
    did not attempt keep their count. Returns the number dead-lettered.
    """
    given_up = 0
    for document_id, outcome in outcomes.items():
        if outcome is not None:
            failed_map.pop(document_id, None)
            continue
        new_count = failed_map.get(document_id, 0) + 1
        if new_count >= MAX_CONSECUTIVE_DOCUMENT_FAILURES:
            log.critical(
                "reconcile.document_given_up",
                document_id=document_id,
                consecutive_failures=new_count,
                advice=(
                    f"giving up on document {document_id} after "
                    f"{new_count} consecutive indexing failures; it will "
                    "be retried only when its content next changes"
                ),
            )
            failed_map.pop(document_id, None)
            given_up += 1
        else:
            failed_map[document_id] = new_count

    _write_failed_documents(store_writer, failed_map)
    return given_up


def _write_failed_documents(
    store_writer: StoreWriter, failed_map: dict[int, int]
) -> None:
    """Persist *failed_map* to store meta as a JSON object with string keys."""
    payload = json.dumps({str(key): value for key, value in failed_map.items()})
    store_writer.write_meta(_FAILED_DOCUMENTS_META_KEY, payload)
