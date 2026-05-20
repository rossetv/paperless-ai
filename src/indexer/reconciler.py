"""Reconciliation engine for the semantic-search indexer.

The reconciler is the indexer's correctness-critical core.  It drives two
operations the daemon loop (SPEC §5.1) calls in turn:

``incremental_sync`` — SPEC §5.2.  Reads the ``modified_watermark`` from store
meta, pages Paperless for everything modified since, refreshes the taxonomy
(SPEC §5.5), and fans the changed documents across a worker pool, isolating
each document's failure (SPEC §5.7).  Whenever the page held a document the
watermark advances to ``max(modified seen) - OVERLAP_MARGIN`` so a timestamp-
boundary document is never missed and re-processing the overlap is free.
Failures do not freeze the watermark: a failed document is recorded in a
persisted ``failed_documents`` map and retried out-of-band each cycle, and is
dead-lettered after ``MAX_DOCUMENT_FAILURES`` consecutive failures — so one
poison document can neither stall forward progress nor re-embed forever.

``deletion_sweep`` — SPEC §5.4.  Enumerates every current Paperless document
id, computes ``store_ids - paperless_ids``, 404-confirms each candidate, and
prunes the confirmed-absent set.  Its safety rule is absolute: if the
enumeration raises at any point, the sweep aborts and prunes NOTHING — a
partial enumeration must never be treated as authoritative, because that would
delete every not-yet-seen document the moment Paperless blips mid-pagination.

Allowed deps: store/ (the StoreWriter), indexer.worker, common/.
Forbidden: sqlite3, httpx, openai direct calls, imports from search/.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from common.clock import utc_now_iso
from indexer.worker import DocumentIndexer, IndexOutcome
from store.models import TaxonomyEntry

if TYPE_CHECKING:
    from common.config import Settings
    from common.embeddings import EmbeddingClient
    from common.paperless import PaperlessClient
    from store.models import IndexState
    from store.writer import StoreWriter

log = structlog.get_logger(__name__)

# How far back the watermark is set relative to the newest document seen
# (SPEC §5.2 step 4).  A few seconds is long enough to absorb a timestamp-
# boundary race between two documents modified in the same instant, and short
# enough that re-processing the overlap is a trivial content-hash no-op.
OVERLAP_MARGIN: timedelta = timedelta(seconds=10)

# How many consecutive cycles a document may fail before the indexer gives up
# on it (dead-letters it).  A document that fails this many times in a row is
# logged at CRITICAL and dropped from the retry map; it will only be retried
# when its Paperless content next changes and the watermark sweep re-includes
# it.  Bounds the per-document retry cost so one poison document cannot freeze
# the watermark or re-embed forever.
MAX_DOCUMENT_FAILURES = 5

# Meta keys owned by the reconciler (SPEC §4.1).
_WATERMARK_META_KEY = "modified_watermark"
_LAST_SWEEP_META_KEY = "last_full_sweep_at"
_LAST_RECONCILE_META_KEY = "last_reconcile_at"
# Maps str(doc_id) -> consecutive_failure_count as a JSON object in store meta.
# Documents that failed to index are retried out-of-band from this map every
# cycle, so forward progress of the watermark is decoupled from failure retry.
_FAILED_DOCUMENTS_META_KEY = "failed_documents"

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
        given_up: Documents that reached ``MAX_DOCUMENT_FAILURES`` consecutive
            failures this cycle and were dead-lettered — dropped from the
            retry map and logged at CRITICAL.  ``given_up`` documents are a
            subset of the cycle's failures and are also counted in ``failed``.
    """

    indexed: int
    metadata_only: int
    skipped: int
    failed: int
    given_up: int


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


class Reconciler:
    """Diffs Paperless-ngx against the search store and keeps the store in sync.

    One instance is created per daemon and reused for every cycle.  It holds no
    per-cycle mutable state; all state lives in the store's meta table or is
    local to a method call.

    Args:
        settings: Application settings.  ``DOCUMENT_WORKERS`` sizes the worker
            pool; the worker reads ``ERROR_TAG_ID``, ``CHUNK_SIZE``, and
            ``CHUNK_OVERLAP`` from the same object.
        paperless: The Paperless API client.  Used read-only here:
            ``iter_all_documents``, the taxonomy lists, and ``document_exists``.
        store_writer: The write-side store API — the sole writer to the index.
        embedding_client: The batched embedding client, forwarded to the
            per-document worker.
    """

    def __init__(
        self,
        settings: Settings,
        paperless: PaperlessClient,
        store_writer: StoreWriter,
        embedding_client: EmbeddingClient,
    ) -> None:
        self._settings = settings
        self._paperless = paperless
        self._store_writer = store_writer
        # The worker is stateless and thread-safe; one instance is shared
        # across the pool for the reconciler's lifetime (SPEC §5.3).
        self._indexer = DocumentIndexer(settings, store_writer, embedding_client)

    # ------------------------------------------------------------------
    # Incremental sync (SPEC §5.2)
    # ------------------------------------------------------------------

    def incremental_sync(self) -> SyncReport:
        """Index every document modified since the watermark, plus retries.

        Reads ``modified_watermark`` from meta and pages Paperless from it
        (epoch — i.e. no filter — on first run, so the first sync is the
        backfill).  Refreshes the taxonomy once (SPEC §5.5).

        The work list for a cycle is two parts:

        1. The watermark page — every document modified since the watermark.
        2. Out-of-band retries — every document id in the persisted
           ``failed_documents`` map that the watermark page did **not** already
           cover.  Each is fetched individually via ``get_document``; an id
           that Paperless reports gone is dropped from the map (the deletion
           sweep handles store cleanup).

        Both parts are fanned across the worker pool with per-document failure
        isolation (SPEC §5.7).  After indexing, the ``failed_documents`` map is
        rebuilt: a document that succeeded is cleared; a document that failed
        has its consecutive-failure count incremented; a document that reaches
        :data:`MAX_DOCUMENT_FAILURES` is logged at CRITICAL and dead-lettered
        (dropped from the map — it is retried only when its content next
        changes and the watermark re-includes it).

        The watermark advances to ``max(modified) - OVERLAP_MARGIN`` whenever
        the watermark page held at least one document — **unconditionally on
        the failure count**, because failures are tracked and retried via the
        ``failed_documents`` map rather than by freezing the watermark.  This
        is what stops one permanently-failing document freezing the watermark
        and re-embedding the whole changed tail every cycle.

        Returns:
            A :class:`SyncReport` with the per-outcome counts.
        """
        watermark = self._store_writer.read_meta(_WATERMARK_META_KEY)
        log.info("reconcile.incremental_started", watermark=watermark)

        # Refresh the taxonomy once per cycle, before document work, so a
        # rename is reflected even on a cycle that indexes nothing (SPEC §5.5).
        self._refresh_taxonomy()

        # Materialise the page stream before fanning out: the worker pool needs
        # the full work list, and a paging failure here propagates as a normal
        # exception (the daemon loop's outer boundary handles it).
        documents = list(
            self._paperless.iter_all_documents(modified_after=watermark)
        )
        page_ids = {doc["id"] for doc in documents}

        # Re-attempt every previously-failed document the watermark page did
        # not already cover.  Ids gone from Paperless are dropped from the map.
        failed_map = self._read_failed_documents()
        retry_documents = self._fetch_retry_documents(failed_map, page_ids)

        # Combine into one work list, deduplicated by id (defensive — the
        # watermark page and the retry set are constructed disjoint).
        work_by_id: dict[int, dict] = {doc["id"]: doc for doc in documents}
        for doc in retry_documents:
            work_by_id.setdefault(doc["id"], doc)

        index_state = self._store_writer.get_index_state()
        outcomes = self._index_documents(list(work_by_id.values()), index_state)

        # Rebuild and persist the failed-document map from this cycle's result.
        given_up = self._update_failed_documents(failed_map, outcomes)

        # Advance the watermark whenever the page held a document — failure
        # retry is decoupled, so a failure no longer freezes the watermark.
        if documents:
            self._advance_watermark(documents)
        else:
            log.info("reconcile.watermark_held", reason="empty_page")

        report = _tally_outcomes(outcomes, given_up=given_up)

        # Mark the index as "ready" (SPEC §4.1).  Written unconditionally at the
        # end of every completed cycle — including cycles where Paperless returned
        # zero documents — because an empty-but-reconciled index is genuinely
        # ready to serve queries.  Without this the search server's healthz check
        # (which gates on last_reconcile_at being non-None) would return 503
        # index-not-ready forever.
        self._store_writer.write_meta(_LAST_RECONCILE_META_KEY, utc_now_iso())

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
        self, documents: list[dict], index_state: dict[int, IndexState]
    ) -> dict[int, IndexOutcome | None]:
        """Fan *documents* across the worker pool and map each id to its outcome.

        Each document is dispatched to :meth:`_index_one`, which catches and
        isolates that document's failure.  The pool is named for log
        correlation (CODE_GUIDELINES §8.6).

        Returns:
            A mapping of document id to its :class:`~indexer.worker.IndexOutcome`,
            or ``None`` for a document whose indexing raised.
        """
        if not documents:
            return {}

        worker_count = max(1, self._settings.DOCUMENT_WORKERS)
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix=_WORKER_THREAD_PREFIX,
        ) as pool:
            results = list(
                pool.map(
                    lambda doc: self._index_one(doc, index_state.get(doc["id"])),
                    documents,
                )
            )
        return dict(results)

    def _index_one(
        self, doc: dict, existing: IndexState | None
    ) -> tuple[int, IndexOutcome | None]:
        """Index one document, isolating any failure (SPEC §5.7).

        Returns ``(document_id, outcome)`` where *outcome* is the worker's
        :class:`~indexer.worker.IndexOutcome` on success, or ``None`` when
        indexing raised — the failure is logged with its traceback and the
        cycle continues with the next document.  The id is returned alongside
        the outcome so the caller can rebuild the failed-document map
        regardless of worker-pool completion order.
        """
        document_id = doc["id"]
        try:
            return document_id, self._indexer.index_document(doc, existing)
        except Exception:
            # rationale: per-document worker dispatch — one document's failure
            # is logged and isolated, the batch continues (CODE_GUIDELINES
            # §6.4 site 2, SPEC §5.7).  The failure is recorded in the
            # failed-document map and retried out-of-band next cycle.
            log.exception("reconcile.document_failed", document_id=document_id)
            return document_id, None

    # ------------------------------------------------------------------
    # Failed-document tracking (SPEC §5.7 — bounded retry / dead-lettering)
    # ------------------------------------------------------------------

    def _read_failed_documents(self) -> dict[int, int]:
        """Read the persisted failed-document map from store meta.

        The map is stored as a JSON object of ``str(doc_id) ->
        consecutive_failure_count``.  A missing key, empty value, or value
        that does not parse as the expected shape yields an empty map — a
        corrupt entry must not crash the cycle; it self-heals as documents
        fail or succeed again.
        """
        raw = self._store_writer.read_meta(_FAILED_DOCUMENTS_META_KEY)
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
            return {int(key): int(value) for key, value in decoded.items()}
        except (ValueError, AttributeError, TypeError):
            # rationale: a corrupt meta value is a recoverable anomaly, not a
            # fatal error — drop it and rebuild from this cycle's outcomes.
            log.warning(
                "reconcile.failed_documents_unreadable", raw_value=raw
            )
            return {}

    def _fetch_retry_documents(
        self, failed_map: dict[int, int], page_ids: set[int]
    ) -> list[dict]:
        """Fetch every failed document the watermark page did not already cover.

        For each id in *failed_map* not in *page_ids*, ``document_exists`` is
        the not-found probe: a ``False`` means the document was deleted from
        Paperless, so it is dropped from *failed_map* in place (the deletion
        sweep prunes the store).  An id that still exists is fetched via
        ``get_document`` and added to the cycle's work list.

        A transport error from either call is isolated per-id (SPEC §5.7): the
        id keeps its current count and is retried next cycle.

        Args:
            failed_map: The failed-document map; **mutated in place** — ids
                confirmed gone from Paperless are removed.
            page_ids: The ids already in the watermark page (skipped here to
                avoid fetching them twice).

        Returns:
            The fetched documents for ids still present in Paperless.
        """
        uncovered = sorted(set(failed_map) - page_ids)
        retry_documents: list[dict] = []
        for document_id in uncovered:
            try:
                if not self._paperless.document_exists(document_id):
                    # Gone from Paperless — stop retrying; the deletion sweep
                    # removes it from the store.
                    del failed_map[document_id]
                    log.info(
                        "reconcile.failed_document_gone",
                        document_id=document_id,
                    )
                    continue
                retry_documents.append(
                    self._paperless.get_document(document_id)
                )
            except Exception:
                # rationale: per-document outer-boundary catch (CODE_GUIDELINES
                # §6.4 site 2) — a transport error re-fetching one failed
                # document must not abort the cycle.  The id keeps its count
                # and is retried next cycle.
                log.exception(
                    "reconcile.failed_document_refetch_failed",
                    document_id=document_id,
                )
        return retry_documents

    def _update_failed_documents(
        self,
        failed_map: dict[int, int],
        outcomes: dict[int, IndexOutcome | None],
    ) -> int:
        """Rebuild and persist the failed-document map from a cycle's outcomes.

        For every document the cycle attempted:

        - **Succeeded** (any non-``None`` outcome) — cleared from the map.
        - **Failed** (``None`` outcome) — its consecutive-failure count is
          incremented.  When the new count reaches :data:`MAX_DOCUMENT_FAILURES`
          the document is logged at CRITICAL and dead-lettered (dropped from
          the map): it is retried only when its content next changes.

        Ids in *failed_map* the cycle did not attempt — e.g. a re-fetch that
        itself failed transiently — keep their existing count untouched.

        Args:
            failed_map: The map to update **in place**; already had
                Paperless-deleted ids removed by :meth:`_fetch_retry_documents`.
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
            if new_count >= MAX_DOCUMENT_FAILURES:
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

        self._write_failed_documents(failed_map)
        return given_up

    def _write_failed_documents(self, failed_map: dict[int, int]) -> None:
        """Persist *failed_map* to store meta as a JSON object.

        Keys are serialised as strings (JSON object keys are always strings);
        :meth:`_read_failed_documents` parses them back to ``int``.
        """
        payload = json.dumps(
            {str(key): value for key, value in failed_map.items()}
        )
        self._store_writer.write_meta(_FAILED_DOCUMENTS_META_KEY, payload)

    def _advance_watermark(self, documents: list[dict]) -> None:
        """Advance the watermark to ``max(modified) - OVERLAP_MARGIN``.

        Only the documents whose ``modified`` field parses as an ISO-8601
        timestamp contribute to the maximum; an unparseable value is logged and
        skipped rather than crashing the cycle.  When no document yields a
        parseable timestamp the watermark is left unchanged.
        """
        latest = _latest_modified(documents)
        if latest is None:
            log.warning("reconcile.watermark_no_parseable_modified")
            return
        new_watermark = (latest - OVERLAP_MARGIN).isoformat()
        self._store_writer.write_meta(_WATERMARK_META_KEY, new_watermark)
        log.info("reconcile.watermark_advanced", watermark=new_watermark)

    # ------------------------------------------------------------------
    # Taxonomy refresh (SPEC §5.5)
    # ------------------------------------------------------------------

    def _refresh_taxonomy(self) -> None:
        """Rebuild the store's taxonomy from the current Paperless lists.

        Fetches correspondents, document types, and tags once, flattens them
        into :class:`~store.models.TaxonomyEntry` rows, and hands the complete
        set to ``StoreWriter.refresh_taxonomy`` — which replaces the table
        atomically, so a Paperless rename is reflected everywhere immediately.
        """
        entries: list[TaxonomyEntry] = []
        entries.extend(
            _to_taxonomy_entries("correspondent", self._paperless.list_correspondents())
        )
        entries.extend(
            _to_taxonomy_entries("document_type", self._paperless.list_document_types())
        )
        entries.extend(_to_taxonomy_entries("tag", self._paperless.list_tags()))
        self._store_writer.refresh_taxonomy(entries)
        log.info("reconcile.taxonomy_refreshed", entry_count=len(entries))

    # ------------------------------------------------------------------
    # Deletion sweep (SPEC §5.4)
    # ------------------------------------------------------------------

    def deletion_sweep(self) -> SweepReport:
        """Prune documents deleted from Paperless — safely.

        Enumerates every current Paperless document id by paging the unfiltered
        list endpoint.  **If the enumeration raises at any point, the sweep
        aborts and prunes NOTHING** (SPEC §5.4 rule 2): a partial enumeration
        would make every not-yet-seen document look deleted, so it is never
        treated as authoritative.

        On a verified-complete enumeration it computes ``store_ids -
        paperless_ids``, confirms each candidate with ``document_exists``
        (a second check against a create-during-enumeration race), prunes the
        confirmed-absent set, and records ``last_full_sweep_at``.

        Returns:
            A :class:`SweepReport`.  ``aborted`` is True and ``pruned`` is 0
            when the enumeration failed.
        """
        log.info("reconcile.sweep_started")

        paperless_ids = self._enumerate_paperless_ids()
        if paperless_ids is None:
            # The enumeration failed — abort and prune nothing.  The next sweep
            # re-attempts the full enumeration from scratch.
            log.warning("reconcile.sweep_aborted", reason="incomplete_enumeration")
            return SweepReport(pruned=0, aborted=True, candidates=0)

        store_ids = self._store_writer.get_all_document_ids()
        candidates = store_ids - paperless_ids

        prune_set = self._confirm_absent(candidates)
        if prune_set:
            self._store_writer.delete_documents(prune_set)

        # Record completion only on a verified-complete sweep.
        self._store_writer.write_meta(_LAST_SWEEP_META_KEY, utc_now_iso())

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

    def _enumerate_paperless_ids(self) -> set[int] | None:
        """Return every current Paperless document id, or ``None`` on failure.

        Pages the unfiltered ``iter_all_documents`` and collects the ids.  The
        whole enumeration is consumed inside one ``try`` so that a failure on
        ANY page — including mid-pagination — yields ``None`` and the caller
        prunes nothing.  This is the load-bearing data-loss guard of SPEC §5.4:
        the set is only returned if it was built to completion.
        """
        try:
            return {
                doc["id"]
                for doc in self._paperless.iter_all_documents()
            }
        except Exception:
            # rationale: outer-boundary catch (CODE_GUIDELINES §6.4) — any
            # enumeration failure must downgrade to "prune nothing", never
            # propagate as a partial id set.  Returning None forces the caller
            # to abort; a partial set could delete the whole archive.
            log.exception("reconcile.enumeration_failed")
            return None

    def _confirm_absent(self, candidates: set[int]) -> set[int]:
        """Return the subset of *candidates* that Paperless confirms is gone.

        For each candidate, ``document_exists`` is the second confirmation
        against a race (SPEC §5.4 rule 3): a document can be missing from the
        page enumeration yet still exist.  A candidate is added to the prune
        set only when ``document_exists`` returns ``False``.  A confirmation
        that itself raises is logged and the candidate is conservatively kept.
        """
        prune_set: set[int] = set()
        for document_id in candidates:
            try:
                still_exists = self._paperless.document_exists(document_id)
            except Exception:
                # rationale: outer-boundary catch (CODE_GUIDELINES §6.4) — a
                # failed confirmation must never be read as "deleted"; keep the
                # document and let the next sweep re-confirm.
                log.exception(
                    "reconcile.confirm_failed", document_id=document_id
                )
                continue
            if not still_exists:
                prune_set.add(document_id)
        return prune_set


# ---------------------------------------------------------------------------
# Module-level helpers (private)
# ---------------------------------------------------------------------------


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
        indexed=sum(1 for o in values if o is IndexOutcome.INDEXED),
        metadata_only=sum(1 for o in values if o is IndexOutcome.METADATA_ONLY),
        skipped=sum(1 for o in values if o is IndexOutcome.SKIPPED),
        failed=sum(1 for o in values if o is None),
        given_up=given_up,
    )


def _to_taxonomy_entries(kind: str, items: list[dict]) -> list[TaxonomyEntry]:
    """Flatten a Paperless taxonomy list into TaxonomyEntry rows.

    Each item is an ``{"id", "name", ...}`` dict from one of the Paperless
    correspondent / document-type / tag list endpoints.  An item missing an
    ``id`` or ``name`` is skipped — the store requires both columns non-null.
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


def _latest_modified(documents: list[dict]) -> datetime | None:
    """Return the newest parseable ``modified`` timestamp across *documents*.

    Returns ``None`` when no document carries a ``modified`` value that
    :func:`datetime.fromisoformat` accepts.  An unparseable value is skipped
    rather than aborting the watermark advance.
    """
    latest: datetime | None = None
    for doc in documents:
        raw = doc.get("modified")
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            log.warning(
                "reconcile.unparseable_modified",
                document_id=doc.get("id"),
                modified=raw,
            )
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest
