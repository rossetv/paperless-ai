"""Bounded failed-document retry and dead-lettering for the reconciler.

SPEC §5.7.  A document whose indexing raises is not allowed either to stall
forward progress or to be retried forever.  This module owns the persisted
``failed_documents`` map — a JSON object of ``str(doc_id) ->
consecutive_failure_count`` in store meta — and the policy around it:

- A failed document is recorded with an incremented consecutive-failure count.
- A previously-failed document the watermark page did not re-cover is
  re-fetched out-of-band each cycle and retried.
- A document that succeeds is cleared from the map.
- A document that reaches :data:`MAX_CONSECUTIVE_DOCUMENT_FAILURES` consecutive
  failures is logged at CRITICAL and dead-lettered (dropped from the map); it
  is retried only when its Paperless content next changes and the watermark
  sweep re-includes it.

The functions take the Paperless client and store writer by argument; the
:class:`~indexer.reconciler.Reconciler` facade owns those instances.
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

# How many consecutive cycles a document may fail before the indexer gives up
# on it (dead-letters it).  A document that fails this many times in a row is
# logged at CRITICAL and dropped from the retry map; it is only retried when
# its Paperless content next changes and the watermark sweep re-includes it.
# Bounds the per-document retry cost so one poison document cannot freeze the
# watermark or re-embed forever.
MAX_CONSECUTIVE_DOCUMENT_FAILURES = 5

# Maps str(doc_id) -> consecutive_failure_count as a JSON object in store meta.
# Documents that failed to index are retried out-of-band from this map every
# cycle, so forward progress of the watermark is decoupled from failure retry.
_FAILED_DOCUMENTS_META_KEY = "failed_documents"


def read_failed_documents(store_writer: StoreWriter) -> dict[int, int]:
    """Read the persisted failed-document map from store meta.

    The map is stored as a JSON object of ``str(doc_id) ->
    consecutive_failure_count``.  A missing key, empty value, or value that
    does not parse as the expected shape yields an empty map — a corrupt entry
    must not crash the cycle; it self-heals as documents fail or succeed again.
    """
    raw = store_writer.read_meta(_FAILED_DOCUMENTS_META_KEY)
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
        return {int(key): int(value) for key, value in decoded.items()}
    except (ValueError, AttributeError, TypeError):
        # rationale: a corrupt meta value is a recoverable anomaly, not a fatal
        # error — drop it and rebuild from this cycle's outcomes.
        log.warning("reconcile.failed_documents_unreadable", raw_value=raw)
        return {}


def fetch_retry_documents(
    paperless: PaperlessClient,
    failed_map: dict[int, int],
    page_ids: set[int],
) -> list[PaperlessDocument]:
    """Fetch every failed document the watermark page did not already cover.

    For each id in *failed_map* not in *page_ids*, ``document_exists`` is the
    not-found probe: a ``False`` means the document was deleted from Paperless,
    so it is dropped from *failed_map* in place (the deletion sweep prunes the
    store).  An id that still exists is fetched via ``get_document`` and added
    to the cycle's work list.

    A transport error from either call is isolated per id (SPEC §5.7): the id
    keeps its current count and is retried next cycle.

    Args:
        paperless: The Paperless API client.
        failed_map: The failed-document map; **mutated in place** — ids
            confirmed gone from Paperless are removed.
        page_ids: The ids already in the watermark page (skipped here to avoid
            fetching them twice).

    Returns:
        The fetched documents for ids still present in Paperless.
    """
    uncovered = sorted(set(failed_map) - page_ids)
    retry_documents: list[PaperlessDocument] = []
    for document_id in uncovered:
        try:
            if not paperless.document_exists(document_id):
                # Gone from Paperless — stop retrying; the deletion sweep
                # removes it from the store.
                del failed_map[document_id]
                log.info("reconcile.failed_document_gone", document_id=document_id)
                continue
            # get_document yields the raw document JSON; the indexer adopts
            # the typed PaperlessDocument view at this boundary (§5.3).
            retry_documents.append(
                cast("PaperlessDocument", paperless.get_document(document_id))
            )
        except PAPERLESS_CALL_EXCEPTIONS:
            # rationale: per-document transport boundary — a network or HTTP
            # error re-fetching one failed document must not abort the cycle.
            # The id keeps its failure count and is retried next cycle.
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
    """Rebuild and persist the failed-document map from a cycle's outcomes.

    For every document the cycle attempted:

    - **Succeeded** (any non-``None`` outcome) — cleared from the map.
    - **Failed** (``None`` outcome) — its consecutive-failure count is
      incremented.  When the new count reaches
      :data:`MAX_CONSECUTIVE_DOCUMENT_FAILURES` the document is logged at
      CRITICAL and dead-lettered (dropped from the map): it is retried only
      when its content next changes.

    Ids in *failed_map* the cycle did not attempt — e.g. a re-fetch that itself
    failed transiently — keep their existing count untouched.

    Args:
        store_writer: The write-side store API.
        failed_map: The map to update **in place**; already had
            Paperless-deleted ids removed by :func:`fetch_retry_documents`.
        outcomes: This cycle's per-id indexing outcomes.

    Returns:
        The number of documents dead-lettered this cycle.
    """
    given_up = 0
    for document_id, outcome in outcomes.items():
        if outcome is not None:
            # Succeeded this cycle — clear any failure history.
            failed_map.pop(document_id, None)
            continue
        # Failed this cycle — increment the consecutive-failure count.
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
    """Persist *failed_map* to store meta as a JSON object.

    Keys are serialised as strings (JSON object keys are always strings);
    :func:`read_failed_documents` parses them back to ``int``.
    """
    payload = json.dumps({str(key): value for key, value in failed_map.items()})
    store_writer.write_meta(_FAILED_DOCUMENTS_META_KEY, payload)
