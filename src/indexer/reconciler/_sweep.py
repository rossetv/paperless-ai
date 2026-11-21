"""Deletion sweep: prune documents deleted from Paperless, safely.

If the Paperless enumeration fails at any point the sweep prunes nothing: a
partial enumeration would make every not-yet-seen document look deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from common.clock import utc_now_iso
from common.paperless import PAPERLESS_CALL_EXCEPTIONS

if TYPE_CHECKING:
    from common.paperless import PaperlessClient
    from store.writer import StoreWriter

log = structlog.get_logger(__name__)

# Wall-clock time the last verified-complete sweep finished.
_LAST_SWEEP_META_KEY = "last_full_sweep_at"


@dataclass(frozen=True, slots=True)
class SweepReport:
    """Outcome of one ``deletion_sweep``.

    Attributes:
        pruned: Documents removed from the store after a 404 confirmation.
        aborted: True when the Paperless enumeration failed and nothing was
            pruned.
        candidates: Store documents missing from the enumeration, before
            confirmation. Zero when the sweep aborted.
    """

    pruned: int
    aborted: bool
    candidates: int


def run_deletion_sweep(
    paperless: PaperlessClient, store_writer: StoreWriter
) -> SweepReport:
    """Prune documents deleted from Paperless.

    On a complete enumeration, each ``store_ids - paperless_ids`` candidate is
    confirmed with ``document_exists`` before pruning, guarding against a
    document created mid-enumeration.
    """
    log.info("reconcile.sweep_started")

    paperless_ids = _enumerate_paperless_ids(paperless)
    if paperless_ids is None:
        log.warning("reconcile.sweep_aborted", reason="incomplete_enumeration")
        return SweepReport(pruned=0, aborted=True, candidates=0)

    store_ids = store_writer.get_all_document_ids()
    candidates = store_ids - paperless_ids

    prune_set = _confirm_absent(paperless, candidates)
    if prune_set:
        store_writer.delete_documents(prune_set)

    store_writer.write_meta(_LAST_SWEEP_META_KEY, utc_now_iso())

    log.info(
        "reconcile.sweep_finished",
        candidates=len(candidates),
        pruned=len(prune_set),
    )
    return SweepReport(
        pruned=len(prune_set),
        aborted=False,
        candidates=len(candidates),
    )


def _enumerate_paperless_ids(paperless: PaperlessClient) -> set[int] | None:
    """Return every current Paperless document id, or ``None`` on failure.

    The whole enumeration runs inside one ``try`` so a failure on any page
    yields ``None``, never a partial set that could delete documents.
    """
    try:
        # Only ids are needed; projecting avoids transferring OCR bodies.
        return {doc["id"] for doc in paperless.iter_all_documents(fields=("id",))}
    except PAPERLESS_CALL_EXCEPTIONS:
        log.exception("reconcile.enumeration_failed")
        return None


def _confirm_absent(paperless: PaperlessClient, candidates: set[int]) -> set[int]:
    """Return the subset of *candidates* that Paperless confirms is gone.

    A confirmation that raises keeps the candidate.
    """
    prune_set: set[int] = set()
    for document_id in candidates:
        try:
            still_exists = paperless.document_exists(document_id)
        except PAPERLESS_CALL_EXCEPTIONS:
            log.exception("reconcile.confirm_failed", document_id=document_id)
            continue
        if not still_exists:
            prune_set.add(document_id)
    return prune_set
