"""Steady-state light-diff — skip byte-for-byte-unchanged re-entered documents.

SPEC §4.2 (IDX-03).  In steady state (a watermark exists) the incremental sync
pages a light ``{id, modified}`` projection of the watermark window instead of
the full documents.  Each row is diffed against the store's already-held
``IndexState.modified``: a row whose ``modified`` is unchanged since the
document was last indexed is **skipped without fetching its OCR body** (the
recurring overlap re-inclusion of classifier-PATCHed documents), and only a
new or genuinely-changed document is fetched in full and run through the
worker's SHA-256 hash gate.

The skip is **fail-safe by construction**: two different ``modified`` instants
cannot normalise to the same string, so a changed document is never skipped; a
normalisation that fails to match merely costs a redundant full fetch — exactly
today's behaviour — never a wrong skip.  The hash gate is therefore never
bypassed for any document whose content reaches the store.

These helpers live in a sibling module of :mod:`._incremental` (CODE_GUIDELINES
§3.1, to keep ``_incremental.py`` under the 500-line ceiling).  The worker
fan-out they need lives in the leaf module :mod:`._fanout`, which both this
module and :mod:`._incremental` import downward — so there is no import cycle
and no injected function pointer.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

import structlog

from common.clock import normalise_paperless_timestamp, parse_paperless_timestamp
from common.paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessDocument
from indexer.reconciler._fanout import _index_documents
from indexer.worker import IndexOutcome

if TYPE_CHECKING:
    from concurrent.futures import ThreadPoolExecutor

    from common.paperless import PaperlessClient
    from indexer.worker import DocumentIndexer
    from store.models import IndexState

log = structlog.get_logger(__name__)

# The light sparse-fieldset projection used for the steady-state diff (IDX-03):
# id + modified only, so the watermark page transfers no OCR content bodies.
# A document is fetched in full (with content) only when its modified advanced.
_LIGHT_DIFF_FIELDS: tuple[str, ...] = ("id", "modified")


# The {id, modified} projection a steady-state watermark page yields — the
# external Paperless wire shape the diff reads, pinned as a TypedDict
# (CODE_GUIDELINES §5.3, mirroring ``PaperlessDocument``) so ``row["id"]`` and
# ``row["modified"]`` are typed rather than bare ``dict`` → ``Any`` access.
class _LightDocumentRow(TypedDict):
    """A light ``{id, modified}`` Paperless projection row (IDX-11).

    Attributes:
        id: The Paperless document id — always present.
        modified: The last-modified timestamp; an ISO-8601 datetime, or absent
            on a malformed upstream row (read defensively, hence NotRequired).
    """

    id: int
    modified: NotRequired[str | None]


def _is_unchanged(existing: IndexState | None, projected_modified: str | None) -> bool:
    """True when a watermark-page row is byte-for-byte unchanged since indexing.

    The IDX-03 skip predicate.  Returns True only when the document already has
    a store row (*existing* is not None) and the projected ``modified``,
    normalised the same way the store normalises it
    (:func:`common.clock.normalise_paperless_timestamp`), exactly equals the
    stored ``modified``.  Paperless bumps ``modified`` on every save, so an
    unchanged ``modified`` means nothing has changed since the document was last
    indexed — it can be skipped without fetching the OCR body.

    Crucially this is **fail-safe**: two different ``modified`` instants cannot
    normalise to the same string, so a genuinely-changed document is never
    reported unchanged.  A normalisation that fails to match (an unrecognised
    format) returns False, so the caller falls back to a full fetch + hash gate
    — i.e. today's behaviour — never a wrong skip.
    """
    if existing is None:
        return False
    return normalise_paperless_timestamp(projected_modified) == existing.modified


def _diff_light_page(
    pool: ThreadPoolExecutor,
    indexer: DocumentIndexer,
    paperless: PaperlessClient,
    light_rows: Iterable[_LightDocumentRow],
    index_state: dict[int, IndexState],
) -> tuple[dict[int, IndexOutcome | None], set[int], datetime | None]:
    """Steady-state diff: skip unchanged rows, fetch + index only changed ones.

    For each light ``{id, modified}`` row from the watermark page:

    - if :func:`_is_unchanged` (existing store row, equal normalised
      ``modified``) → **skip**: no OCR body is fetched and no store write
      happens (the IDX-03 win for re-entered, classifier-PATCHed documents);
    - otherwise (new id, or ``modified`` advanced) → fetch the full document via
      ``get_document`` and run it through the worker, whose SHA-256 hash gate
      decides metadata-only vs re-embed.

    Every row contributes its ``modified`` to the running maximum so the
    watermark advances past skipped documents too (otherwise a skipped boundary
    document would re-enter forever).

    A ``get_document`` failure for one changed id is isolated per document
    (SPEC §5.7): it is recorded as a ``None`` outcome and the cycle continues.

    Args:
        pool: The cycle-scoped worker pool (built by
            :func:`._incremental.run_incremental_sync`) the changed set is
            fanned across via :func:`._fanout._index_documents`.
        indexer: The stateless per-document worker.
        paperless: The Paperless API client (for the lazy ``get_document``).
        light_rows: The ``{id, modified}`` rows from the projected watermark page.
        index_state: The store's id → ``IndexState`` map.

    Returns:
        ``(outcomes, page_ids, latest_modified)`` — the per-id outcomes (a
        skipped id is absent from ``outcomes``; it produced no work), the set of
        every row id seen on the page, and the newest parseable ``modified``.
    """
    outcomes: dict[int, IndexOutcome | None] = {}
    page_ids: set[int] = set()
    latest_modified: datetime | None = None
    to_fetch: list[int] = []

    for row in light_rows:
        document_id = row["id"]
        page_ids.add(document_id)
        latest_modified = _fold_modified(
            latest_modified, row.get("modified"), document_id
        )
        if _is_unchanged(index_state.get(document_id), row.get("modified")):
            continue
        to_fetch.append(document_id)

    if to_fetch:
        skipped = len(page_ids) - len(to_fetch)
        log.info(
            "reconcile.steady_state_skipped",
            skipped=skipped,
            to_fetch=len(to_fetch),
        )
        changed_documents = _fetch_full_documents(paperless, to_fetch, outcomes)
        outcomes.update(_index_documents(pool, indexer, changed_documents, index_state))
    else:
        log.info("reconcile.steady_state_all_unchanged", skipped=len(page_ids))

    return outcomes, page_ids, latest_modified


def _fetch_full_documents(
    paperless: PaperlessClient,
    document_ids: list[int],
    outcomes: dict[int, IndexOutcome | None],
) -> list[PaperlessDocument]:
    """Fetch each changed document in full; isolate a per-id fetch failure.

    A transport error fetching one document is recorded as a ``None`` outcome in
    *outcomes* (so the failed-document map picks it up) and the id is skipped —
    the cycle continues (SPEC §5.7).  The returned list is the documents that
    fetched successfully, ready for the worker fan-out.
    """
    fetched: list[PaperlessDocument] = []
    for document_id in document_ids:
        try:
            fetched.append(
                cast("PaperlessDocument", paperless.get_document(document_id))
            )
        except PAPERLESS_CALL_EXCEPTIONS:
            # rationale: per-document transport boundary — a failure fetching one
            # changed document must not abort the cycle.  Record it as a failure
            # so it is retried out-of-band next cycle (SPEC §5.7).
            log.exception(
                "reconcile.changed_document_fetch_failed", document_id=document_id
            )
            outcomes[document_id] = None
    return fetched


def _fold_modified(
    latest: datetime | None, raw: str | None, document_id: int | None
) -> datetime | None:
    """Fold one raw ``modified`` string into the running maximum.

    The single implementation shared by the per-row steady-state diff
    (:func:`_diff_light_page`) and the batch full-document path
    (:func:`~indexer.reconciler._incremental._fold_latest_modified`).

    If *raw* is absent or empty the running *latest* is returned unchanged (the
    document simply does not advance the watermark).  An unparseable value is
    logged at WARNING and skipped, so a malformed upstream timestamp never
    aborts the watermark advance.  Returns the new running maximum.

    Args:
        latest: The running maximum so far (``None`` if nothing parseable has
            been seen yet).
        raw: The ``modified`` string from the Paperless API row, or ``None``.
        document_id: The Paperless document id — included in the warning log so
            the operator can identify the offending document.
    """
    if not raw:
        return latest
    parsed = parse_paperless_timestamp(raw)
    if parsed is None:
        log.warning(
            "reconcile.unparseable_modified", document_id=document_id, modified=raw
        )
        return latest
    if latest is None or parsed > latest:
        return parsed
    return latest
