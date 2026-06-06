"""Tests for indexer.reconciler incremental sync — the watermark-driven core.

incremental_sync (SPEC §5.2):
- Reads the modified_watermark, pages Paperless from it, fans documents across
  a worker pool, and advances the watermark when the page held a document.
- The watermark overlap re-includes a boundary document next cycle; the
  content-hash gate makes that re-inclusion a cheap METADATA_ONLY no-op.
- A changed document is re-indexed.
- A single failing document is isolated and counted; the cycle continues, and
  a mid-pagination failure leaves the watermark unmoved.

The taxonomy refresh, the last_reconcile_at write, and the report shape live in
test_reconciler_incremental_cycle.py; the bounded failed-document retry in
test_reconciler_failed_documents.py; the deletion sweep in
test_reconciler_sweep.py — the reconciler's tests are split across files to
stay under the 500-line ceiling (CODE_GUIDELINES §3.1, §11.2).  The Paperless
and StoreWriter mock builders, ``always_indexed``, and ``run_incremental_sync``
come from tests/unit/indexer/conftest.py.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from common.clock import normalise_paperless_timestamp
from indexer.reconciler import OVERLAP_MARGIN
from indexer.worker import IndexOutcome
from store.models import IndexState
from tests.helpers.factories import make_paperless_document
from tests.unit.indexer.conftest import (
    always_indexed,
    make_reconciler_paperless,
    make_reconciler_store_writer,
    run_incremental_sync,
)


def _hash_gated_index_document(
    _self: object, doc: dict, existing: IndexState | None
) -> IndexOutcome:
    """A DocumentIndexer.index_document stub that mirrors the content-hash gate.

    Returns ``METADATA_ONLY`` when *existing* carries the document's current
    content hash, ``INDEXED`` otherwise — the same branch the real
    :meth:`indexer.worker.DocumentIndexer.index_document` takes.  Usable
    directly as a ``monkeypatch.setattr`` value for the method.
    """
    doc_hash = hashlib.sha256(doc["content"].encode()).hexdigest()
    if existing is not None and existing.content_hash == doc_hash:
        return IndexOutcome.METADATA_ONLY
    return IndexOutcome.INDEXED


# ---------------------------------------------------------------------------
# incremental_sync — indexing new documents and advancing the watermark
# ---------------------------------------------------------------------------


class TestIncrementalSyncIndexesNewDocuments:
    """A first cycle indexes every returned document and advances the watermark."""

    def test_new_documents_are_indexed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        docs = [
            make_paperless_document(doc_id=1),
            make_paperless_document(doc_id=2),
        ]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer()

        index_calls: list[int] = []

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            index_calls.append(doc["id"])
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert sorted(index_calls) == [1, 2]
        assert report.indexed == 2
        assert report.failed == 0

    def test_watermark_advances_to_max_modified_minus_overlap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fully-successful pass advances the watermark to max(modified) - OVERLAP."""
        latest = "2024-06-10T08:30:00+00:00"
        docs = [
            make_paperless_document(doc_id=1, modified="2024-06-01T00:00:00+00:00"),
            make_paperless_document(doc_id=2, modified=latest),
        ]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer()

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        expected = (datetime.fromisoformat(latest) - OVERLAP_MARGIN).isoformat()
        assert store_writer._meta["modified_watermark"] == expected

    def test_first_run_reads_no_watermark_and_queries_from_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no stored watermark, iter_all_documents is called with modified_after=None."""
        paperless = make_reconciler_paperless(
            documents=[make_paperless_document(doc_id=1)]
        )
        store_writer = make_reconciler_store_writer(watermark=None)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        incremental_calls = [
            call
            for call in paperless.iter_all_documents.call_args_list
            if call.kwargs.get("modified_after") is None
        ]
        # The deletion sweep is not run here; only the incremental call exists,
        # and on first run its modified_after is None.
        assert len(incremental_calls) == 1

    def test_stored_watermark_is_passed_as_modified_after(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In steady state the watermark is the modified_after, with the light projection.

        A stored watermark selects the steady-state path (IDX-03): the page is
        the light ``{id, modified}`` projection, so the call carries both
        ``modified_after=watermark`` and ``fields=_LIGHT_DIFF_FIELDS``.
        """
        from indexer.reconciler._light_diff import _LIGHT_DIFF_FIELDS

        watermark = "2024-05-01T00:00:00+00:00"
        paperless = make_reconciler_paperless(documents=[])
        store_writer = make_reconciler_store_writer(watermark=watermark)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        paperless.iter_all_documents.assert_called_once_with(
            modified_after=watermark, fields=_LIGHT_DIFF_FIELDS
        )

    def test_empty_cycle_does_not_change_the_watermark(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No documents returned → nothing to advance to → watermark untouched."""
        watermark = "2024-05-01T00:00:00+00:00"
        paperless = make_reconciler_paperless(documents=[])
        store_writer = make_reconciler_store_writer(watermark=watermark)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        report = run_incremental_sync(paperless, store_writer)

        assert store_writer._meta["modified_watermark"] == watermark
        assert report.indexed == 0


# ---------------------------------------------------------------------------
# incremental_sync — the watermark overlap and the content-hash gate
# ---------------------------------------------------------------------------


class TestIncrementalSyncWatermarkOverlap:
    """The overlap re-includes a boundary document; the hash gate makes it cheap."""

    def test_boundary_document_reincluded_is_skipped_cold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A re-included boundary document with an unchanged modified is skipped.

        In steady state (IDX-03) the overlap re-inclusion is even cheaper than a
        metadata-only update: a document whose projected ``modified`` equals the
        stored ``modified`` is skipped cold — its OCR body is never fetched and
        the worker is never invoked, so it certainly cannot be re-embedded.  The
        watermark still advances over it (covered by
        ``TestSkipStillAdvancesWatermark``).
        """
        content = "Stable boundary content."
        boundary_modified = "2024-06-01T12:00:00+00:00"
        boundary_doc = make_paperless_document(
            doc_id=7, modified=boundary_modified, content=content
        )
        paperless = make_reconciler_paperless(documents=[boundary_doc])

        existing_hash = hashlib.sha256(content.encode()).hexdigest()
        index_state = {
            7: IndexState(
                modified=normalise_paperless_timestamp(boundary_modified),
                content_hash=existing_hash,
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark=boundary_modified, index_state=index_state
        )

        captured_existing: list[IndexState | None] = []

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            captured_existing.append(existing)
            return _hash_gated_index_document(_self, doc, existing)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        # The boundary document was skipped: the worker never ran and the OCR
        # body was never fetched — no re-embed, no metadata write.
        assert captured_existing == []
        paperless.get_document.assert_not_called()
        assert report.indexed == 0
        assert report.metadata_only == 0

    def test_changed_document_is_reindexed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A document whose content hash differs from the store is re-indexed."""
        changed_doc = make_paperless_document(
            doc_id=3, content="Brand new content body."
        )
        paperless = make_reconciler_paperless(documents=[changed_doc])

        # The store holds a stale hash for document 3.
        index_state = {
            3: IndexState(
                modified="2024-05-01T00:00:00+00:00",
                content_hash="stale-hash-does-not-match",
            )
        }
        store_writer = make_reconciler_store_writer(index_state=index_state)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            _hash_gated_index_document,
        )

        report = run_incremental_sync(paperless, store_writer)

        assert report.indexed == 1
        assert report.metadata_only == 0


# ---------------------------------------------------------------------------
# incremental_sync — per-document failure isolation (SPEC §5.7)
# ---------------------------------------------------------------------------


class TestIncrementalSyncIsolatesFailures:
    """A single failing document never aborts the cycle (SPEC §5.7)."""

    def test_one_failing_document_does_not_abort_the_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs = [make_paperless_document(doc_id=i) for i in (1, 2, 3)]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer()

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            if doc["id"] == 2:
                raise RuntimeError("embedding API exploded for document 2")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        # Documents 1 and 3 still indexed; 2 counted as failed.
        assert report.indexed == 2
        assert report.failed == 1

    def test_skipped_documents_are_counted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs = [make_paperless_document(doc_id=i) for i in (1, 2)]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer()

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            if doc["id"] == 1:
                return IndexOutcome.SKIPPED
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert report.skipped == 1
        assert report.indexed == 1

    def test_partial_incremental_enumeration_leaves_watermark_unmoved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mid-pagination failure during INCREMENTAL sync must not move the watermark.

        The incremental page is materialised before any document is indexed.
        If that generator yields one document then raises mid-pagination, the
        failure propagates out of incremental_sync (the daemon's cycle boundary
        catches it), and the watermark must be byte-for-byte unchanged.
        """
        watermark = "2024-05-01T00:00:00+00:00"
        store_writer = make_reconciler_store_writer(watermark=watermark)

        paperless = MagicMock()

        def _iter_all_documents(**kwargs: object):
            # Incremental call (modified_after present): yield one, then fail.
            yield make_paperless_document(
                doc_id=1, modified="2024-06-09T00:00:00+00:00"
            )
            raise ConnectionError("Paperless dropped mid-incremental-pagination")

        paperless.iter_all_documents.side_effect = _iter_all_documents
        paperless.list_correspondents.return_value = []
        paperless.list_document_types.return_value = []
        paperless.list_tags.return_value = []

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        # The paging failure propagates — the daemon's cycle boundary handles it.
        with pytest.raises(ConnectionError):
            run_incremental_sync(paperless, store_writer)

        # The watermark is exactly where it started.
        assert store_writer._meta["modified_watermark"] == watermark


# ---------------------------------------------------------------------------
# incremental_sync — the watermark page is streamed, not materialised
# ---------------------------------------------------------------------------


class TestIncrementalSyncStreamsThePageStream:
    """The watermark page is consumed in batches, not materialised whole.

    Regression: ``run_incremental_sync`` used to wrap the lazy
    ``iter_all_documents`` generator in ``list()``, materialising the entire
    OCR corpus — every document's full ``content`` body — into RAM at once.  On
    a first-run backfill (watermark ``None`` → no server filter) that pulled the
    whole archive into memory and OOM-killed the daemon host.  The sync must now
    pull one ``page_size`` batch, index it, drop it, then pull the next — so
    indexing interleaves with paging and memory is O(one batch).
    """

    def test_indexing_interleaves_with_paging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Indexing of an early batch begins before the whole stream is paged.

        The document source is a real generator that records, at each ``yield``,
        how many documents the worker has already indexed.  With the old
        ``list()`` materialisation the generator is fully drained before a
        single ``index_document`` call fires, so every recorded count is 0.
        With batched streaming the first batch is indexed before the tail of
        the stream is paged, so a later ``yield`` sees a non-zero count.
        """
        # Two full batches plus one — enough that the first batch is indexed
        # and dropped before the generator is exhausted.
        from indexer.reconciler._incremental import _WATERMARK_PAGE_BATCH_SIZE

        total = _WATERMARK_PAGE_BATCH_SIZE * 2 + 1
        indexed_count = 0
        # Index calls recorded at each yield point of the document generator.
        counts_at_yield: list[int] = []

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            nonlocal indexed_count
            indexed_count += 1
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        def _document_stream(**kwargs: object):
            for doc_id in range(1, total + 1):
                counts_at_yield.append(indexed_count)
                yield make_paperless_document(doc_id=doc_id)

        paperless = MagicMock()
        paperless.iter_all_documents.side_effect = _document_stream
        paperless.list_correspondents.return_value = []
        paperless.list_document_types.return_value = []
        paperless.list_tags.return_value = []
        paperless.document_exists.return_value = False
        store_writer = make_reconciler_store_writer()

        report = run_incremental_sync(paperless, store_writer)

        assert report.indexed == total
        # The decisive assertion: by the time the final document is yielded the
        # worker has already indexed at least the first batch.  Under the old
        # ``list()`` implementation every count is 0 — the whole stream is
        # drained before indexing starts — and this fails.
        assert counts_at_yield[-1] >= _WATERMARK_PAGE_BATCH_SIZE

    def test_retry_documents_reuse_the_batched_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Out-of-band retry documents are indexed and counted like page docs.

        After streaming the watermark page the sync still fetches and indexes
        every previously-failed document the page did not cover — the streaming
        refactor must not regress that out-of-band retry path.
        """
        # The watermark page holds doc 1; doc 2 is a previously-failed retry.
        paperless = make_reconciler_paperless(
            documents=[make_paperless_document(doc_id=1)]
        )
        paperless.document_exists.return_value = True
        paperless.get_document.return_value = make_paperless_document(doc_id=2)
        store_writer = make_reconciler_store_writer()
        store_writer._meta["failed_documents"] = '{"2": 1}'

        indexed_ids: list[int] = []

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            indexed_ids.append(doc["id"])
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        # Both the page document and the out-of-band retry were indexed.
        assert sorted(indexed_ids) == [1, 2]
        assert report.indexed == 2


# ---------------------------------------------------------------------------
# SACRED INVARIANTS — pinned before any efficiency change (spec §7)
# ---------------------------------------------------------------------------


class TestSacredInvariantsBaseline:
    """I1/I2: the SHA-256 hash gate decides embed vs metadata-only.

    These pin the contract the IDX-03 light-diff must preserve, exercised
    through the real steady-state path:

    - I1 (never re-embed unchanged work): a re-entered document whose
      ``modified`` is unchanged is skipped cold — never fetched, never embedded.
    - I2 (metadata-only change takes the no-embed path): a document whose
      ``modified`` advanced but whose content is byte-for-byte identical is
      fetched, hash-gated, and routed to ``update_metadata`` — never re-embedded.
    """

    def test_unchanged_content_is_never_reembedded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """I1: a re-entered document with an unchanged modified embeds nothing.

        In steady state the document is skipped before the worker, so it is
        never even handed to the SHA-256 gate — the strongest possible form of
        "unchanged content is never re-embedded".
        """
        content = "Stable content body."
        modified = "2024-06-01T12:00:00+00:00"
        doc = make_paperless_document(doc_id=5, content=content, modified=modified)
        paperless = _light_paperless(
            full_docs=[doc], light_rows=[{"id": 5, "modified": modified}]
        )
        index_state = {
            5: IndexState(
                modified=normalise_paperless_timestamp(modified),
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark=modified, index_state=index_state
        )

        embedded: list[int] = []

        def _index_document(
            _self: object, d: dict, existing: IndexState | None
        ) -> IndexOutcome:
            # Mirror the real worker's gate exactly.
            doc_hash = hashlib.sha256(d["content"].encode()).hexdigest()
            if existing is not None and existing.content_hash == doc_hash:
                return IndexOutcome.METADATA_ONLY
            embedded.append(d["id"])
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert embedded == []  # I1: never re-embedded
        paperless.get_document.assert_not_called()  # never even fetched
        assert report.indexed == 0
        assert report.metadata_only == 0  # skipped, not even a metadata write

    def test_metadata_only_change_takes_the_no_embed_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """I2: content identical, metadata advanced → METADATA_ONLY, not INDEXED.

        The document's ``modified`` advanced (a metadata PATCH), so the
        steady-state diff fetches it and runs the SHA-256 gate; identical content
        means the gate routes it to the no-embed metadata-only path.
        """
        content = "Identical content."
        old_modified = "2024-06-01T00:00:00+00:00"
        new_modified = "2024-07-01T00:00:00+00:00"
        doc = make_paperless_document(
            doc_id=6, content=content, modified=new_modified
        )
        paperless = _light_paperless(
            full_docs=[doc], light_rows=[{"id": 6, "modified": new_modified}]
        )
        index_state = {
            6: IndexState(
                modified=normalise_paperless_timestamp(old_modified),
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark="2024-05-01T00:00:00+00:00", index_state=index_state
        )

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            _hash_gated_index_document,
        )

        report = run_incremental_sync(paperless, store_writer)

        paperless.get_document.assert_called_once_with(6)  # fetched lazily
        assert report.metadata_only == 1
        assert report.indexed == 0


# ---------------------------------------------------------------------------
# IDX-03 guard tests (G1–G4) — steady-state light-diff (spec §7)
# These FAIL until Task 6 lands the steady-state projection path.
# ---------------------------------------------------------------------------


def _light_paperless(
    *, full_docs: list[dict], light_rows: list[dict]
) -> MagicMock:
    """A Paperless mock that returns light {id, modified} rows on the watermark
    page and full documents from get_document(id).

    iter_all_documents(modified_after=..., fields=...) → light_rows when a
    `fields` projection is requested, else full_docs. get_document(id) returns
    the matching full document.
    """
    paperless = MagicMock()
    by_id = {doc["id"]: doc for doc in full_docs}

    def _iter(**kwargs: object) -> list[dict]:
        if "modified_after" not in kwargs:
            # Deletion-sweep style call (no incremental keyword) — ids only.
            return [{"id": doc_id} for doc_id in by_id]
        if kwargs.get("fields") is not None:
            return list(light_rows)
        return list(full_docs)

    paperless.iter_all_documents.side_effect = _iter
    paperless.get_document.side_effect = lambda doc_id: by_id[doc_id]
    paperless.document_exists.return_value = True
    paperless.list_correspondents.return_value = []
    paperless.list_document_types.return_value = []
    paperless.list_tags.return_value = []
    return paperless


class TestSteadyStateLightDiff:
    """In steady state, unchanged re-entered documents are skipped cold."""

    def test_steady_state_skip_never_embeds_or_fetches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """G/I1: a byte-for-byte-unchanged re-entered doc is neither fetched nor embedded."""
        modified = "2024-06-01T12:00:00+00:00"
        full = make_paperless_document(doc_id=7, content="x", modified=modified)
        paperless = _light_paperless(
            full_docs=[full], light_rows=[{"id": 7, "modified": modified}]
        )
        # The store already holds this doc with the SAME normalised modified.
        from common.clock import normalise_paperless_timestamp

        index_state = {
            7: IndexState(
                modified=normalise_paperless_timestamp(modified),
                content_hash="whatever",
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark=modified, index_state=index_state
        )

        calls: list[int] = []

        def _index_document(
            _self: object, d: dict, existing: IndexState | None
        ) -> IndexOutcome:
            calls.append(d["id"])
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert calls == []  # never run through the worker
        paperless.get_document.assert_not_called()  # OCR body never fetched
        assert report.indexed == 0
        assert report.metadata_only == 0

    def test_changed_modified_same_content_is_metadata_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """I2: a doc whose modified advanced is fetched, hash-gated, metadata-only."""
        content = "Identical body."
        old_modified = "2024-06-01T00:00:00+00:00"
        new_modified = "2024-07-01T00:00:00+00:00"
        full = make_paperless_document(
            doc_id=8, content=content, modified=new_modified
        )
        paperless = _light_paperless(
            full_docs=[full], light_rows=[{"id": 8, "modified": new_modified}]
        )
        from common.clock import normalise_paperless_timestamp

        index_state = {
            8: IndexState(
                modified=normalise_paperless_timestamp(old_modified),
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark="2024-05-01T00:00:00+00:00", index_state=index_state
        )

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            _hash_gated_index_document,
        )

        report = run_incremental_sync(paperless, store_writer)

        paperless.get_document.assert_called_once_with(8)  # fetched lazily
        assert report.metadata_only == 1
        assert report.indexed == 0


class TestFirstRunBackfillGuard:
    """G1: first-run backfill keeps the full-document page path."""

    def test_first_run_backfill_pages_full_documents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no watermark, iter_all_documents is called WITHOUT a fields projection."""
        docs = [make_paperless_document(doc_id=i) for i in (1, 2)]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer(watermark=None)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        report = run_incremental_sync(paperless, store_writer)

        # The incremental call carried no `fields` projection (full bodies).
        incremental = [
            call
            for call in paperless.iter_all_documents.call_args_list
            if "modified_after" in call.kwargs
        ]
        assert len(incremental) == 1
        assert incremental[0].kwargs.get("fields") is None
        # get_document is NOT used as a per-id fetch on first run.
        paperless.get_document.assert_not_called()
        assert report.indexed == 2


class TestLightDiffIsFailSafe:
    """G2: an unrecognisable modified format degrades to a full fetch, never a skip."""

    def test_unrecognised_modified_format_falls_back_to_full_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If projected modified can't be matched, the doc is fetched and hash-gated."""
        content = "Body."
        full = make_paperless_document(
            doc_id=9, content=content, modified="2024-06-01T00:00:00+00:00"
        )
        # The light row carries a garbage modified the normaliser keeps verbatim,
        # which will NOT equal the store's normalised value.
        paperless = _light_paperless(
            full_docs=[full], light_rows=[{"id": 9, "modified": "not-a-timestamp"}]
        )
        index_state = {
            9: IndexState(
                modified="2024-06-01T00:00:00+00:00",
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark="2024-05-01T00:00:00+00:00", index_state=index_state
        )

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            _hash_gated_index_document,
        )

        report = run_incremental_sync(paperless, store_writer)

        # Fell back to a full fetch + hash gate (status quo), did not skip.
        paperless.get_document.assert_called_once_with(9)
        assert report.metadata_only == 1


class TestSkipStillAdvancesWatermark:
    """G3: a cycle that skips every document still advances the watermark."""

    def test_skipped_documents_still_advance_the_watermark(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from common.clock import normalise_paperless_timestamp

        modified = "2024-06-10T08:30:00+00:00"
        full = make_paperless_document(doc_id=10, content="x", modified=modified)
        paperless = _light_paperless(
            full_docs=[full], light_rows=[{"id": 10, "modified": modified}]
        )
        index_state = {
            10: IndexState(
                modified=normalise_paperless_timestamp(modified),
                content_hash="h",
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark="2024-05-01T00:00:00+00:00", index_state=index_state
        )

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        expected = (
            datetime.fromisoformat(modified) - OVERLAP_MARGIN
        ).isoformat()
        assert store_writer._meta["modified_watermark"] == expected


class TestChangedFetchFailureIsolated:
    """G4: a get_document failure for one changed id is isolated (SPEC §5.7)."""

    def test_changed_document_fetch_failure_is_isolated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from common.paperless import PAPERLESS_CALL_EXCEPTIONS  # noqa: F401

        good = make_paperless_document(
            doc_id=11, content="a", modified="2024-07-01T00:00:00+00:00"
        )
        # Both ids have advanced modified → both are "changed" → both fetched.
        paperless = _light_paperless(
            full_docs=[good],
            light_rows=[
                {"id": 11, "modified": "2024-07-01T00:00:00+00:00"},
                {"id": 12, "modified": "2024-07-02T00:00:00+00:00"},
            ],
        )

        def _get_document(doc_id: int) -> dict:
            if doc_id == 12:
                raise ConnectionError("Paperless dropped fetching doc 12")
            return good

        paperless.get_document.side_effect = _get_document
        store_writer = make_reconciler_store_writer(
            watermark="2024-05-01T00:00:00+00:00", index_state={}
        )

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        report = run_incremental_sync(paperless, store_writer)

        # Doc 11 indexed; doc 12's fetch failure is isolated and counted.
        assert report.indexed == 1
        assert report.failed == 1


# ---------------------------------------------------------------------------
# _is_unchanged — the load-bearing skip predicate (spec §4.2)
# ---------------------------------------------------------------------------


class TestIsUnchangedPredicate:
    """The skip predicate matches only on equal NORMALISED modified values."""

    def test_equal_after_normalisation_is_unchanged(self) -> None:
        from common.clock import normalise_paperless_timestamp
        from indexer.reconciler._light_diff import _is_unchanged

        existing = IndexState(
            modified=normalise_paperless_timestamp("2024-06-01T12:00:00Z"),
            content_hash="h",
        )
        # A different wire format for the SAME instant must compare equal.
        assert _is_unchanged(existing, "2024-06-01T12:00:00+00:00") is True

    def test_different_instant_is_not_unchanged(self) -> None:
        from common.clock import normalise_paperless_timestamp
        from indexer.reconciler._light_diff import _is_unchanged

        existing = IndexState(
            modified=normalise_paperless_timestamp("2024-06-01T12:00:00Z"),
            content_hash="h",
        )
        assert _is_unchanged(existing, "2024-07-01T00:00:00+00:00") is False

    def test_none_existing_is_not_unchanged(self) -> None:
        from indexer.reconciler._light_diff import _is_unchanged

        # A document with no store row is new — never "unchanged".
        assert _is_unchanged(None, "2024-06-01T12:00:00+00:00") is False

    def test_unparseable_projected_modified_is_not_unchanged(self) -> None:
        from indexer.reconciler._light_diff import _is_unchanged

        existing = IndexState(modified="2024-06-01T12:00:00+00:00", content_hash="h")
        # A garbage projected value the normaliser keeps verbatim will not equal
        # the store's normalised value → fall back to a full fetch (not a skip).
        assert _is_unchanged(existing, "not-a-timestamp") is False
