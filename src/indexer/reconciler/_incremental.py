"""Incremental sync — indexing every document modified since the watermark.

SPEC §5.2.  ``run_incremental_sync`` reads the ``modified_watermark`` from
store meta, pages Paperless for everything modified since, refreshes the
taxonomy (SPEC §5.5), and fans the changed documents across a worker pool,
isolating each document's failure (SPEC §5.7).  Whenever the page held a
document the watermark advances to ``max(modified seen) - OVERLAP_MARGIN`` so a
timestamp-boundary document is never missed and re-processing the overlap is
free.

Failures do not freeze the watermark: a failed document is recorded in the
persisted ``failed_documents`` map (see :mod:`._failed_documents`) and retried
out-of-band each cycle.  The watermark advances unconditionally on the failure
count, so one poison document can neither stall forward progress nor re-embed
the changed tail forever.

The functions take the Paperless client, store writer, and per-document worker
by argument; the :class:`~indexer.reconciler.Reconciler` facade owns those.
"""

from __future__ import annotations

import functools
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

import structlog

from common.clock import parse_paperless_timestamp, utc_now_iso
from common.paperless import PaperlessDocument, PaperlessItem
from indexer.reconciler import _failed_documents
from indexer.worker import IndexOutcome
from store.models import TaxonomyEntry

if TYPE_CHECKING:
    from common.paperless import PaperlessClient
    from indexer.worker import DocumentIndexer
    from store.models import IndexState
    from store.writer import StoreWriter

log = structlog.get_logger(__name__)

# How far back the watermark is set relative to the newest document seen
# (SPEC §5.2 step 4).  A few seconds is long enough to absorb a timestamp-
# boundary race between two documents modified in the same instant, and short
# enough that re-processing the overlap is a trivial content-hash no-op.
OVERLAP_MARGIN: timedelta = timedelta(seconds=10)

# Meta keys owned by the incremental sync (SPEC §4.1).
_WATERMARK_META_KEY = "modified_watermark"
_LAST_RECONCILE_META_KEY = "last_reconcile_at"

# Thread-pool name so log correlation and profilers can attribute the work
# (CODE_GUIDELINES §8.6).
_WORKER_THREAD_PREFIX = "indexer-document"


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Outcome counts for one ``incremental_sync`` cycle.

    The counts span both the watermark-driven page sync and the out-of-band
    re-attempt of previously-failed documents — a document re-attempted from
    the failed-document map and indexed this cycle counts under ``indexed``.

    Attributes:
        indexed: Documents fully chunked, embedded, and upserted.
        metadata_only: Documents whose content hash was unchanged — only the
            metadata columns were updated, no re-embed.
        skipped: Documents the worker gated out (empty content or error tag).
        failed: Documents whose indexing raised this cycle; isolated and
            counted, the cycle continued (SPEC §5.7).  Each is tracked in the
            failed-document map and retried next cycle.
        given_up: Documents that reached
            :data:`~indexer.reconciler._failed_documents.MAX_CONSECUTIVE_DOCUMENT_FAILURES`
            consecutive failures this cycle and were dead-lettered — dropped
            from the retry map and logged at CRITICAL.  ``given_up`` documents
            are a subset of the cycle's failures and are also counted in
            ``failed``.
    """

    indexed: int
    metadata_only: int
    skipped: int
    failed: int
    given_up: int


def run_incremental_sync(
    paperless: PaperlessClient,
    store_writer: StoreWriter,
    indexer: DocumentIndexer,
    worker_count: int,
) -> SyncReport:
    """Index every document modified since the watermark, plus retries.

    Reads ``modified_watermark`` from meta and pages Paperless from it (epoch —
    i.e. no filter — on first run, so the first sync is the backfill).
    Refreshes the taxonomy once (SPEC §5.5).

    The work list for a cycle is two parts:

    1. The watermark page — every document modified since the watermark.
    2. Out-of-band retries — every document id in the persisted
       ``failed_documents`` map that the watermark page did **not** already
       cover (see :mod:`._failed_documents`).

    Both parts are fanned across the worker pool with per-document failure
    isolation (SPEC §5.7).  After indexing, the ``failed_documents`` map is
    rebuilt.

    The watermark advances to ``max(modified) - OVERLAP_MARGIN`` whenever the
    watermark page held at least one document — **unconditionally on the
    failure count**, because failures are tracked and retried via the
    ``failed_documents`` map rather than by freezing the watermark.

    Args:
        paperless: The Paperless API client.
        store_writer: The write-side store API — the sole writer to the index.
        indexer: The stateless per-document worker, shared across the pool.
        worker_count: Size of the worker pool (``DOCUMENT_WORKERS``).

    Returns:
        A :class:`SyncReport` with the per-outcome counts.
    """
    watermark = store_writer.read_meta(_WATERMARK_META_KEY)
    log.info("reconcile.incremental_started", watermark=watermark)

    # Refresh the taxonomy once per cycle, before document work, so a rename is
    # reflected even on a cycle that indexes nothing (SPEC §5.5).
    _refresh_taxonomy(paperless, store_writer)

    # Materialise the page stream before fanning out: the worker pool needs the
    # full work list, and a paging failure here propagates as a normal
    # exception (the daemon loop's outer boundary handles it).  The Paperless
    # client yields the raw document JSON; this is the boundary at which the
    # indexer adopts the typed PaperlessDocument view of that foreign shape
    # (CODE_GUIDELINES §5.3).
    documents = cast(
        "list[PaperlessDocument]",
        list(paperless.iter_all_documents(modified_after=watermark)),
    )
    page_ids = {doc["id"] for doc in documents}

    # Re-attempt every previously-failed document the watermark page did not
    # already cover.  Ids gone from Paperless are dropped from the map.
    failed_map = _failed_documents.read_failed_documents(store_writer)
    retry_documents = _failed_documents.fetch_retry_documents(
        paperless, failed_map, page_ids
    )

    # Combine into one work list, deduplicated by id (defensive — the watermark
    # page and the retry set are constructed disjoint).
    work_by_id: dict[int, PaperlessDocument] = {
        doc["id"]: doc for doc in documents
    }
    for doc in retry_documents:
        work_by_id.setdefault(doc["id"], doc)

    index_state = store_writer.get_index_state()
    outcomes = _index_documents(
        indexer, list(work_by_id.values()), index_state, worker_count
    )

    # Rebuild and persist the failed-document map from this cycle's result.
    given_up = _failed_documents.update_failed_documents(
        store_writer, failed_map, outcomes
    )

    # Advance the watermark whenever the page held a document — failure retry
    # is decoupled, so a failure no longer freezes the watermark.
    if documents:
        _advance_watermark(store_writer, documents)
    else:
        log.info("reconcile.watermark_held", reason="empty_page")

    report = _tally_outcomes(outcomes, given_up=given_up)

    # Mark the index as "ready" (SPEC §4.1).  Written unconditionally at the
    # end of every completed cycle — including cycles where Paperless returned
    # zero documents — because an empty-but-reconciled index is genuinely ready
    # to serve queries.  Without this the search server's healthz check (which
    # gates on last_reconcile_at being non-None) would return 503
    # index-not-ready forever.
    store_writer.write_meta(_LAST_RECONCILE_META_KEY, utc_now_iso())

    log.info(
        "reconcile.incremental_finished",
        indexed=report.indexed,
        metadata_only=report.metadata_only,
        skipped=report.skipped,
        failed=report.failed,
        given_up=report.given_up,
    )
    return report


def _index_documents(
    indexer: DocumentIndexer,
    documents: list[PaperlessDocument],
    index_state: dict[int, IndexState],
    worker_count: int,
) -> dict[int, IndexOutcome | None]:
    """Fan *documents* across the worker pool and map each id to its outcome.

    Each document is dispatched to :func:`_index_one`, which catches and
    isolates that document's failure.  The pool is named for log correlation
    (CODE_GUIDELINES §8.6).

    Returns:
        A mapping of document id to its :class:`~indexer.worker.IndexOutcome`,
        or ``None`` for a document whose indexing raised.
    """
    if not documents:
        return {}

    pool_size = max(1, worker_count)
    # A partial binds the indexer and index_state; only the per-document arg
    # varies across the map, which keeps the dispatch readable (no lambda
    # closing over loop state — CODE_GUIDELINES §1.1).
    index_one = functools.partial(_index_one, indexer, index_state)
    with ThreadPoolExecutor(
        max_workers=pool_size,
        thread_name_prefix=_WORKER_THREAD_PREFIX,
    ) as pool:
        results = list(pool.map(index_one, documents))
    return dict(results)


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
        return document_id, indexer.index_document(
            doc, index_state.get(document_id)
        )
    except Exception:
        # rationale: per-document worker dispatch — one document's failure is
        # logged and isolated, the batch continues (CODE_GUIDELINES §6.4
        # site 2, SPEC §5.7).  The failure is recorded in the failed-document
        # map and retried out-of-band next cycle.
        log.exception("reconcile.document_failed", document_id=document_id)
        return document_id, None


def _advance_watermark(
    store_writer: StoreWriter, documents: list[PaperlessDocument]
) -> None:
    """Advance the watermark to ``max(modified) - OVERLAP_MARGIN``.

    Only the documents whose ``modified`` field parses as an ISO-8601 timestamp
    contribute to the maximum; an unparseable value is logged and skipped
    rather than crashing the cycle.  When no document yields a parseable
    timestamp the watermark is left unchanged.
    """
    latest = _latest_modified(documents)
    if latest is None:
        log.warning("reconcile.watermark_no_parseable_modified")
        return
    new_watermark = (latest - OVERLAP_MARGIN).isoformat()
    store_writer.write_meta(_WATERMARK_META_KEY, new_watermark)
    log.info("reconcile.watermark_advanced", watermark=new_watermark)


def _refresh_taxonomy(
    paperless: PaperlessClient, store_writer: StoreWriter
) -> None:
    """Rebuild the store's taxonomy from the current Paperless lists.

    Fetches correspondents, document types, and tags once, flattens them into
    :class:`~store.models.TaxonomyEntry` rows, and hands the complete set to
    ``StoreWriter.refresh_taxonomy`` — which replaces the table atomically, so
    a Paperless rename is reflected everywhere immediately.
    """
    entries: list[TaxonomyEntry] = []
    entries.extend(
        _to_taxonomy_entries("correspondent", paperless.list_correspondents())
    )
    entries.extend(
        _to_taxonomy_entries("document_type", paperless.list_document_types())
    )
    entries.extend(_to_taxonomy_entries("tag", paperless.list_tags()))
    store_writer.refresh_taxonomy(entries)
    log.info("reconcile.taxonomy_refreshed", entry_count=len(entries))


def _tally_outcomes(
    outcomes: dict[int, IndexOutcome | None], *, given_up: int
) -> SyncReport:
    """Aggregate per-id indexing *outcomes* into a :class:`SyncReport`.

    A ``None`` outcome is an isolated per-document failure (SPEC §5.7).

    Args:
        outcomes: Mapping of document id to its outcome (``None`` on failure).
        given_up: The count of documents dead-lettered this cycle — carried
            through onto the report; a subset of the failures.
    """
    values = list(outcomes.values())
    return SyncReport(
        indexed=sum(1 for outcome in values if outcome is IndexOutcome.INDEXED),
        metadata_only=sum(
            1 for outcome in values if outcome is IndexOutcome.METADATA_ONLY
        ),
        skipped=sum(1 for outcome in values if outcome is IndexOutcome.SKIPPED),
        failed=sum(1 for outcome in values if outcome is None),
        given_up=given_up,
    )


def _to_taxonomy_entries(
    kind: str, items: list[PaperlessItem]
) -> list[TaxonomyEntry]:
    """Flatten a Paperless taxonomy list into TaxonomyEntry rows.

    Each item is a :class:`~common.paperless.PaperlessItem` from one of the
    Paperless correspondent / document-type / tag list endpoints.  The ``id`` /
    ``name`` checks are kept as a runtime guard against a malformed upstream
    row (CODE_GUIDELINES §1.11, fail-closed): the store requires both columns
    non-null, so a defective item is skipped rather than persisted.
    """
    entries: list[TaxonomyEntry] = []
    for entry in items:
        entry_id = entry.get("id")
        name = entry.get("name")
        if entry_id is None or name is None:
            log.warning(
                "reconcile.taxonomy_entry_skipped", kind=kind, entry=entry
            )
            continue
        entries.append(TaxonomyEntry(kind=kind, id=entry_id, name=name))
    return entries


def _latest_modified(documents: list[PaperlessDocument]) -> datetime | None:
    """Return the newest parseable ``modified`` timestamp across *documents*.

    Each ``modified`` value is run through
    :func:`common.clock.parse_paperless_timestamp` — the shared Paperless-
    timestamp normaliser — so the maximum is computed over UTC-aware datetimes.
    Returns ``None`` when no document carries a parseable ``modified`` value;
    an unparseable value is logged and skipped rather than aborting the
    watermark advance.
    """
    latest: datetime | None = None
    for doc in documents:
        raw = doc.get("modified")
        if not raw:
            continue
        parsed = parse_paperless_timestamp(raw)
        if parsed is None:
            log.warning(
                "reconcile.unparseable_modified",
                document_id=doc.get("id"),
                modified=raw,
            )
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest
