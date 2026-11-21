"""Incremental sync: index every document modified since the watermark.

The page stream is consumed in fixed-size batches, never materialised whole: on
a first-run backfill it is the entire archive with full OCR text, enough to
OOM-kill the host. Failed documents are retried out-of-band (see
``_failed_documents``), so a failure never freezes the watermark.
"""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, TypeVar, cast

import structlog

from common.clock import utc_now_iso
from common.paperless import PaperlessDocument, PaperlessItem
from indexer.reconciler import _failed_documents
from indexer.reconciler._fanout import _WORKER_THREAD_PREFIX, _index_documents
from indexer.reconciler._light_diff import (
    _LIGHT_DIFF_FIELDS,
    _LightDocumentRow,
    _diff_light_page,
    _fold_modified,
)
from indexer.worker import IndexOutcome
from store.models import TaxonomyEntry

if TYPE_CHECKING:
    from common.paperless import PaperlessClient
    from indexer.worker import DocumentIndexer
    from store.models import IndexState
    from store.writer import StoreWriter

log = structlog.get_logger(__name__)

# How far behind the newest document seen the watermark is set: enough to
# absorb a timestamp-boundary race, and re-processing the overlap is a cheap
# content-hash no-op.
OVERLAP_MARGIN: timedelta = timedelta(seconds=10)

_WATERMARK_META_KEY = "modified_watermark"
_LAST_RECONCILE_META_KEY = "last_reconcile_at"

# Matches the Paperless API page_size, so one batch is one HTTP page of OCR
# bodies in RAM.
_WATERMARK_PAGE_BATCH_SIZE = 100

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Outcome counts for one ``incremental_sync`` cycle, retries included.

    Attributes:
        indexed: Documents fully chunked, embedded, and upserted.
        metadata_only: Content hash unchanged; only metadata was updated.
        skipped: Documents the worker gated out (empty content or error tag).
        failed: Documents whose indexing raised; retried next cycle.
        given_up: Failures dead-lettered this cycle; also counted in ``failed``.
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
    """Index every document modified since the watermark, plus failed retries.

    With no watermark (first run) the sync is a full backfill. The watermark
    advances to ``max(modified) - OVERLAP_MARGIN`` whenever the page held a
    document, regardless of failures; retried documents do not move it.
    """
    watermark = store_writer.read_meta(_WATERMARK_META_KEY)
    log.info("reconcile.incremental_started", watermark=watermark)

    # Before document work, so a rename lands even on a cycle that indexes
    # nothing.
    _refresh_taxonomy(paperless, store_writer)

    # id -> (modified, content_hash): cheap, so read once and shared by batches.
    index_state = store_writer.get_index_state()

    # One pool per cycle, reused across every batch and the retry pass, rather
    # than one per 100-document batch.
    pool_size = max(1, worker_count)
    with ThreadPoolExecutor(
        max_workers=pool_size,
        thread_name_prefix=_WORKER_THREAD_PREFIX,
    ) as pool:
        # Backfill pages full documents: every body is needed anyway, and a
        # light projection would turn one paged list into N per-id fetches.
        # Steady state pages the light {id, modified} projection and fetches
        # bodies only for documents that actually changed.
        if watermark is None:
            page_stream = cast(
                "Iterator[PaperlessDocument]",
                paperless.iter_all_documents(modified_after=watermark),
            )
            outcomes, page_ids, latest_modified = _index_page_stream(
                pool, indexer, page_stream, index_state
            )
        else:
            light_rows = cast(
                "Iterator[_LightDocumentRow]",
                paperless.iter_all_documents(
                    modified_after=watermark, fields=_LIGHT_DIFF_FIELDS
                ),
            )
            outcomes, page_ids, latest_modified = _diff_light_page(
                pool,
                indexer,
                paperless,
                light_rows,
                index_state,
            )

        failed_map = _failed_documents.read_failed_documents(store_writer)
        retry_documents = _failed_documents.fetch_retry_documents(
            paperless, failed_map, page_ids
        )
        for batch in _batched(retry_documents, _WATERMARK_PAGE_BATCH_SIZE):
            outcomes.update(_index_documents(pool, indexer, list(batch), index_state))

    given_up = _failed_documents.update_failed_documents(
        store_writer, failed_map, outcomes
    )

    if page_ids:
        _advance_watermark(store_writer, latest_modified)
    else:
        log.info("reconcile.watermark_held", reason="empty_page")

    report = _tally_outcomes(outcomes, given_up=given_up)

    # Written even when Paperless returned nothing: an empty reconciled index
    # is ready, and the search server's healthz gates on this key.
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
    pool: ThreadPoolExecutor,
    indexer: DocumentIndexer,
    page_stream: Iterator[PaperlessDocument],
    index_state: dict[int, IndexState],
) -> tuple[dict[int, IndexOutcome | None], set[int], datetime | None]:
    """Index the full-document page stream one batch at a time.

    Each batch is dropped before the next is paged, so peak memory is one batch.
    Returns ``(outcomes, page_ids, latest_modified)``; *latest_modified* is
    ``None`` when no document had a parseable timestamp.
    """
    outcomes: dict[int, IndexOutcome | None] = {}
    page_ids: set[int] = set()
    latest_modified: datetime | None = None
    for batch in _batched(page_stream, _WATERMARK_PAGE_BATCH_SIZE):
        documents = list(batch)
        outcomes.update(_index_documents(pool, indexer, documents, index_state))
        page_ids.update(doc["id"] for doc in documents)
        latest_modified = _fold_latest_modified(latest_modified, documents)
        log.info("reconcile.page_batch_indexed", batch_size=len(documents))
    return outcomes, page_ids, latest_modified


def _advance_watermark(store_writer: StoreWriter, latest: datetime | None) -> None:
    """Advance the watermark to ``latest - OVERLAP_MARGIN``; keep it if ``None``."""
    if latest is None:
        log.warning("reconcile.watermark_no_parseable_modified")
        return
    new_watermark = (latest - OVERLAP_MARGIN).isoformat()
    store_writer.write_meta(_WATERMARK_META_KEY, new_watermark)
    log.info("reconcile.watermark_advanced", watermark=new_watermark)


def _refresh_taxonomy(paperless: PaperlessClient, store_writer: StoreWriter) -> None:
    """Replace the store's taxonomy atomically from the current Paperless lists."""
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
    """Aggregate per-id *outcomes* (``None`` = failed) into a :class:`SyncReport`."""
    counts = Counter(outcomes.values())
    return SyncReport(
        indexed=counts[IndexOutcome.INDEXED],
        metadata_only=counts[IndexOutcome.METADATA_ONLY],
        skipped=counts[IndexOutcome.SKIPPED],
        failed=counts[None],
        given_up=given_up,
    )


def _to_taxonomy_entries(
    kind: Literal["correspondent", "document_type", "tag"],
    items: list[PaperlessItem],
) -> list[TaxonomyEntry]:
    """Flatten a Paperless taxonomy list into TaxonomyEntry rows.

    An item missing ``id`` or ``name`` is skipped: the store requires both.
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
    """Fold a batch's ``modified`` timestamps into the running maximum *latest*."""
    for doc in documents:
        latest = _fold_modified(latest, doc.get("modified"), doc.get("id"))
    return latest


def _batched(items: Iterable[_T], batch_size: int) -> Iterator[tuple[_T, ...]]:
    """Yield *items* lazily in tuples of at most *batch_size*.

    Stand-in for :func:`itertools.batched`, which needs Python 3.12.
    """
    iterator = iter(items)
    while batch := tuple(itertools.islice(iterator, batch_size)):
        yield batch
