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
        watermark = "2024-05-01T00:00:00+00:00"
        paperless = make_reconciler_paperless(documents=[])
        store_writer = make_reconciler_store_writer(watermark=watermark)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        paperless.iter_all_documents.assert_called_once_with(modified_after=watermark)

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

    def test_boundary_document_reincluded_is_a_metadata_only_no_op(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A re-included boundary document with an unchanged hash → METADATA_ONLY.

        The worker decides METADATA_ONLY when the existing IndexState's
        content_hash matches.  The reconciler must pass that existing state so
        the gate fires and the re-inclusion is free (no re-embed).
        """
        content = "Stable boundary content."
        boundary_modified = "2024-06-01T12:00:00+00:00"
        boundary_doc = make_paperless_document(
            doc_id=7, modified=boundary_modified, content=content
        )
        paperless = make_reconciler_paperless(documents=[boundary_doc])

        existing_hash = hashlib.sha256(content.encode()).hexdigest()
        index_state = {
            7: IndexState(modified=boundary_modified, content_hash=existing_hash)
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

        # The reconciler passed the document's existing IndexState.
        assert captured_existing == [index_state[7]]
        # The hash gate fired: a cheap metadata-only update, not a re-index.
        assert report.metadata_only == 1
        assert report.indexed == 0

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
