"""The deletion sweep — pruning documents deleted from Paperless, safely.

SPEC §5.4.  ``run_deletion_sweep`` enumerates every current Paperless document
id, computes ``store_ids - paperless_ids``, 404-confirms each candidate, and
prunes the confirmed-absent set.  Its safety rule is absolute: if the
enumeration raises at any point, the sweep aborts and prunes NOTHING — a
partial enumeration must never be treated as authoritative, because that would
delete every not-yet-seen document the moment Paperless blips mid-pagination.

The functions take the Paperless client and store writer by argument; the
:class:`~indexer.reconciler.Reconciler` facade owns those instances.
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

# Meta key recording the wall-clock time the last verified-complete sweep
# finished (SPEC §4.1).
_LAST_SWEEP_META_KEY = "last_full_sweep_at"


@dataclass(frozen=True, slots=True)
class SweepReport:
    """Outcome of one ``deletion_sweep``.

    Attributes:
        pruned: Documents removed from the store — present in the store, absent
            from Paperless, and 404-confirmed absent.
        aborted: True when the Paperless enumeration failed; the sweep pruned
            nothing because a partial enumeration is never authoritative
            (SPEC §5.4 rule 2).
        candidates: Documents that were in the store but not in the (complete)
            enumeration — the set fed to per-id 404 confirmation.  Zero when
            the sweep aborted.
    """

    pruned: int
    aborted: bool
    candidates: int


def run_deletion_sweep(
    paperless: PaperlessClient, store_writer: StoreWriter
) -> SweepReport:
    """Prune documents deleted from Paperless — safely.

    Enumerates every current Paperless document id by paging the unfiltered
    list endpoint.  **If the enumeration raises at any point, the sweep aborts
    and prunes NOTHING** (SPEC §5.4 rule 2): a partial enumeration would make
    every not-yet-seen document look deleted, so it is never treated as
    authoritative.

    On a verified-complete enumeration it computes ``store_ids -
    paperless_ids``, confirms each candidate with ``document_exists`` (a second
    check against a create-during-enumeration race), prunes the
    confirmed-absent set, and records ``last_full_sweep_at``.

    Returns:
        A :class:`SweepReport`.  ``aborted`` is True and ``pruned`` is 0 when
        the enumeration failed.
    """
    log.info("reconcile.sweep_started")

    paperless_ids = _enumerate_paperless_ids(paperless)
    if paperless_ids is None:
        # The enumeration failed — abort and prune nothing.  The next sweep
        # re-attempts the full enumeration from scratch.
        log.warning("reconcile.sweep_aborted", reason="incomplete_enumeration")
        return SweepReport(pruned=0, aborted=True, candidates=0)

    store_ids = store_writer.get_all_document_ids()
    candidates = store_ids - paperless_ids

    prune_set = _confirm_absent(paperless, candidates)
    if prune_set:
        store_writer.delete_documents(prune_set)

    # Record completion only on a verified-complete sweep.
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

    Pages the unfiltered ``iter_all_documents`` and collects the ids.  The
    whole enumeration is consumed inside one ``try`` so that a failure on ANY
    page — including mid-pagination — yields ``None`` and the caller prunes
    nothing.  This is the load-bearing data-loss guard of SPEC §5.4: the set is
    only returned if it was built to completion.
    """
    try:
        # fields=("id",): the sweep needs only the id set, so project away every
        # other field — notably the OCR content body — for a strictly smaller
        # enumeration transfer (IDX-03 perf). Behaviour is unchanged.
        return {doc["id"] for doc in paperless.iter_all_documents(fields=("id",))}
    except PAPERLESS_CALL_EXCEPTIONS:
        # rationale: Paperless transport boundary — any enumeration failure
        # must downgrade to "prune nothing", never propagate as a partial id
        # set.  Returning None forces the caller to abort; a partial set could
        # delete documents from the archive (SPEC §5.4 rule 2).
        log.exception("reconcile.enumeration_failed")
        return None


def _confirm_absent(paperless: PaperlessClient, candidates: set[int]) -> set[int]:
    """Return the subset of *candidates* that Paperless confirms is gone.

    For each candidate, ``document_exists`` is the second confirmation against
    a race (SPEC §5.4 rule 3): a document can be missing from the page
    enumeration yet still exist.  A candidate is added to the prune set only
    when ``document_exists`` returns ``False``.  A confirmation that itself
    raises is logged and the candidate is conservatively kept.
    """
    prune_set: set[int] = set()
    for document_id in candidates:
        try:
            still_exists = paperless.document_exists(document_id)
        except PAPERLESS_CALL_EXCEPTIONS:
            # rationale: Paperless transport boundary — a failed confirmation
            # must never be treated as "deleted"; keep the document and let the
            # next sweep re-confirm (SPEC §5.4 rule 3).
            log.exception("reconcile.confirm_failed", document_id=document_id)
            continue
        if not still_exists:
            prune_set.add(document_id)
    return prune_set
