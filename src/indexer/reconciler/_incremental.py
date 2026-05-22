"""Incremental sync — indexing every document modified since the watermark.

SPEC §5.2.  ``run_incremental_sync`` reads the ``modified_watermark`` from
store meta, pages Paperless for everything modified since, refreshes the
taxonomy (SPEC §5.5), and fans the changed documents across a worker pool,
isolating each document's failure (SPEC §5.7).  Whenever the page held a
document the watermark advances to ``max(modified seen) - OVERLAP_MARGIN`` so a
timestamp-boundary document is never missed and re-processing the overlap is
free.

The page stream is **never materialised whole**.  ``iter_all_documents`` is a
lazy generator that pages Paperless at ``page_size=100``; each
:class:`~common.paperless.PaperlessDocument` carries the document's full OCR
text in its ``content`` field.  On a first-run backfill (watermark ``None`` →
no server-side filter) that is the entire archive — materialising it OOM-kills
the daemon host.  The sync therefore consumes the stream in fixed-size
batches: a batch is indexed through the worker pool, its outcomes and ids are
folded into cycle-wide accumulators, and the batch is then dropped so its
document bodies are freed before the next batch is paged.  Peak memory is
O(one batch), not O(whole archive).

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
import itertools
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, TypeVar, cast

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

# How many documents the watermark page stream is consumed in at a time.  Set
# to the Paperless API ``page_size`` so one batch is one HTTP page: the indexer
# holds at most one page of OCR bodies in RAM at once, never the whole archive.
# (``itertools.batched`` would express this, but it is 3.12+ and the target
# runtime is 3.11 — see :func:`_batched`.)
_WATERMARK_PAGE_BATCH_SIZE = 100

# Generic element type for the :func:`_batched` streaming helper.
_T = TypeVar("_T")


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

    The work for a cycle is two parts:

    1. The watermark page — every document modified since the watermark.  This
       stream is **never materialised whole**: it is consumed in fixed-size
       batches (:data:`_WATERMARK_PAGE_BATCH_SIZE`), each batch indexed and
       then dropped so its OCR bodies are freed before the next batch is paged.
    2. Out-of-band retries — every document id in the persisted
       ``failed_documents`` map that the watermark page did **not** already
       cover (see :mod:`._failed_documents`).  This set is bounded by the
       failed-map size; it reuses the same batched indexing path.

    Both parts are fanned across the worker pool with per-document failure
    isolation (SPEC §5.7).  After indexing, the ``failed_documents`` map is
    rebuilt from the cycle-wide outcomes covering both parts.

    The watermark advances to ``max(modified) - OVERLAP_MARGIN`` whenever the
    watermark page held at least one document — **unconditionally on the
    failure count**, because failures are tracked and retried via the
    ``failed_documents`` map rather than by freezing the watermark.  Only the
    watermark-page documents contribute to that maximum; retry documents do
    not influence the watermark.

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

    # The index state is id -> (modified, content_hash) — cheap, no OCR bodies —
    # so it is read once upfront and shared by every batch's worker fan-out.
    index_state = store_writer.get_index_state()

    # Stream the watermark page in batches.  The Paperless client yields the raw
    # document JSON; this is the boundary at which the indexer adopts the typed
    # PaperlessDocument view of that foreign shape (CODE_GUIDELINES §5.3).  A
    # paging failure mid-stream propagates as a normal exception — the daemon
    # loop's outer boundary handles it; it is not swallowed here.
    page_stream = cast(
        "Iterator[PaperlessDocument]",
        paperless.iter_all_documents(modified_after=watermark),
    )
    outcomes, page_ids, latest_modified = _index_page_stream(
        indexer, page_stream, index_state, worker_count
    )

    # Re-attempt every previously-failed document the watermark page did not
    # already cover.  Ids gone from Paperless are dropped from the map.
    failed_map = _failed_documents.read_failed_documents(store_writer)
    retry_documents = _failed_documents.fetch_retry_documents(
        paperless, failed_map, page_ids
    )
    # Retry documents are bounded by the failed-map size; index them through the
    # same batched path for consistency and merge their outcomes into the
    # cycle-wide dict.  They do NOT influence the watermark (see below).
    for batch in _batched(retry_documents, _WATERMARK_PAGE_BATCH_SIZE):
        outcomes.update(
            _index_documents(indexer, list(batch), index_state, worker_count)
        )

    # Rebuild and persist the failed-document map from this cycle's result.
    given_up = _failed_documents.update_failed_documents(
        store_writer, failed_map, outcomes
    )

    # Advance the watermark whenever the page held a document — failure retry
    # is decoupled, so a failure no longer freezes the watermark.  Only the
    # watermark-page documents feed ``latest_modified``; retries are excluded.
    if page_ids:
        _advance_watermark(store_writer, latest_modified)
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


def _index_page_stream(
    indexer: DocumentIndexer,
    page_stream: Iterator[PaperlessDocument],
    index_state: dict[int, IndexState],
    worker_count: int,
) -> tuple[dict[int, IndexOutcome | None], set[int], datetime | None]:
    """Consume the watermark page stream in batches and index each batch.

    The stream is the lazy ``iter_all_documents`` generator — every document
    carries its full OCR ``content``.  Materialising it whole would hold the
    entire archive in RAM (the OOM bug this function exists to prevent), so it
    is consumed :data:`_WATERMARK_PAGE_BATCH_SIZE` documents at a time.  For
    each batch:

    - the batch is fanned across the worker pool via :func:`_index_documents`,
    - its outcomes are merged into the cycle-wide ``outcomes`` dict,
    - its document ids are added to the cycle-wide ``page_ids`` set,
    - its ``modified`` timestamps are folded into a running maximum,

    and the batch is then dropped, so its document bodies are freed before the
    next batch is paged.  Peak memory is O(one batch).

    A paging failure mid-stream propagates as a normal exception (the daemon
    loop's outer boundary handles it); it is not swallowed.

    Returns:
        A triple ``(outcomes, page_ids, latest_modified)`` — the per-id
        indexing outcomes across every batch, the set of every page document
        id, and the newest parseable ``modified`` timestamp seen (``None`` when
        the stream was empty or carried no parseable timestamp).
    """
    outcomes: dict[int, IndexOutcome | None] = {}
    page_ids: set[int] = set()
    latest_modified: datetime | None = None
    for batch in _batched(page_stream, _WATERMARK_PAGE_BATCH_SIZE):
        # list(): the batch is the unit of work and is dropped at the end of
        # this iteration — at most one page of OCR bodies is resident at once.
        documents = list(batch)
        outcomes.update(_index_documents(indexer, documents, index_state, worker_count))
        page_ids.update(doc["id"] for doc in documents)
        latest_modified = _fold_latest_modified(latest_modified, documents)
        log.info("reconcile.page_batch_indexed", batch_size=len(documents))
    return outcomes, page_ids, latest_modified


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
        return document_id, indexer.index_document(doc, index_state.get(document_id))
    except Exception:
        # rationale: per-document worker dispatch — one document's failure is
        # logged and isolated, the batch continues (CODE_GUIDELINES §6.4
        # site 2, SPEC §5.7).  The failure is recorded in the failed-document
        # map and retried out-of-band next cycle.
        log.exception("reconcile.document_failed", document_id=document_id)
        return document_id, None


def _advance_watermark(store_writer: StoreWriter, latest: datetime | None) -> None:
    """Advance the watermark to ``latest - OVERLAP_MARGIN``.

    *latest* is the running maximum of the watermark-page documents' parseable
    ``modified`` timestamps, folded batch by batch as the page stream was
    consumed (see :func:`_fold_latest_modified`).  An unparseable value was
    logged and skipped during that fold rather than crashing the cycle.  When
    *latest* is ``None`` — no page document yielded a parseable timestamp — the
    watermark is left unchanged.
    """
    if latest is None:
        log.warning("reconcile.watermark_no_parseable_modified")
        return
    new_watermark = (latest - OVERLAP_MARGIN).isoformat()
    store_writer.write_meta(_WATERMARK_META_KEY, new_watermark)
    log.info("reconcile.watermark_advanced", watermark=new_watermark)


def _refresh_taxonomy(paperless: PaperlessClient, store_writer: StoreWriter) -> None:
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


def _to_taxonomy_entries(kind: str, items: list[PaperlessItem]) -> list[TaxonomyEntry]:
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
            log.warning("reconcile.taxonomy_entry_skipped", kind=kind, entry=entry)
            continue
        entries.append(TaxonomyEntry(kind=kind, id=entry_id, name=name))
    return entries


def _fold_latest_modified(
    latest: datetime | None, documents: list[PaperlessDocument]
) -> datetime | None:
    """Fold a batch's ``modified`` timestamps into a running maximum.

    Folds the newest parseable ``modified`` timestamp across *documents* into
    *latest* (the running maximum carried across batches), so the watermark's
    maximum is computed without ever holding more than one batch of documents
    in memory.  Each ``modified`` value is run through
    :func:`common.clock.parse_paperless_timestamp` — the shared Paperless-
    timestamp normaliser — so the maximum is over UTC-aware datetimes.  An
    unparseable value is logged and skipped rather than aborting the watermark
    advance; when neither *latest* nor any document carries a parseable value
    the result is ``None`` and the watermark is left unchanged by the caller.
    """
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


def _batched(items: Iterable[_T], batch_size: int) -> Iterator[tuple[_T, ...]]:
    """Yield *items* in tuples of at most *batch_size*, lazily.

    A 3.11-compatible stand-in for :func:`itertools.batched` (3.12+).  The
    source iterable is consumed lazily — one batch is pulled, yielded, and only
    when the caller asks for the next is the following batch paged — which is
    what keeps the reconciler's peak memory at O(one batch) rather than
    O(whole archive).  The final batch may be shorter; an empty source yields
    nothing.
    """
    iterator = iter(items)
    while batch := tuple(itertools.islice(iterator, batch_size)):
        yield batch
