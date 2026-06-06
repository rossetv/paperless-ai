"""Tests for indexer.reconciler bounded failed-document retry (SPEC §5.7).

A permanently-failing document is retried, bounded, and dead-lettered.  The old
design froze the watermark on any failure — a document that failed every cycle
stalled the watermark forever and re-embedded the whole growing changed tail.
The fix decouples forward progress from failure retry: the watermark advances
unconditionally, while failed documents are tracked in a persisted
``failed_documents`` map, retried out-of-band each cycle, and dead-lettered
after :data:`~indexer.reconciler.MAX_CONSECUTIVE_DOCUMENT_FAILURES` consecutive
failures.

The incremental sync proper lives in test_reconciler_incremental.py; the
deletion sweep in test_reconciler_sweep.py — the reconciler's tests mirror the
indexer/reconciler/ package split (CODE_GUIDELINES §11.2).
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
import structlog.testing

from indexer.reconciler import (
    MAX_CONSECUTIVE_DOCUMENT_FAILURES,
    OVERLAP_MARGIN,
    Reconciler,
)
from indexer.worker import IndexOutcome
from store.models import IndexState
from tests.helpers.factories import make_paperless_document, make_settings_obj
from tests.helpers.mocks import make_mock_embedding_client
from tests.unit.indexer.conftest import (
    make_reconciler_paperless,
    make_reconciler_store_writer,
)


class TestIncrementalSyncFailedDocumentRetry:
    """A permanently-failing document is retried, bounded, and dead-lettered."""

    def test_failing_document_advances_watermark_and_is_tracked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failure no longer freezes the watermark — it advances unconditionally.

        Forward progress is decoupled from failure retry: a page that held a
        document advances the watermark to ``max(modified) - OVERLAP`` even
        when one document failed, and the failed document is recorded in the
        persisted ``failed_documents`` map for an out-of-band retry next cycle.
        """
        watermark = "2024-05-01T00:00:00+00:00"
        latest = "2024-06-10T00:00:00+00:00"
        docs = [
            make_paperless_document(doc_id=1, modified="2024-06-09T00:00:00+00:00"),
            make_paperless_document(doc_id=2, modified=latest),
        ]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer(watermark=watermark)

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            if doc["id"] == 2:
                raise RuntimeError("document 2 failed")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = Reconciler(
            make_settings_obj(),
            paperless,
            store_writer,
            make_mock_embedding_client(),
        ).incremental_sync()

        assert report.failed == 1
        assert report.given_up == 0
        # The watermark advanced despite the failure.
        expected = (datetime.fromisoformat(latest) - OVERLAP_MARGIN).isoformat()
        assert store_writer._meta["modified_watermark"] == expected
        # The failed document is recorded for retry with one consecutive failure.
        assert json.loads(store_writer._meta["failed_documents"]) == {"2": 1}

    def test_permanently_failing_document_is_retried_then_dead_lettered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A document that fails every cycle is retried via the failed-id set,
        dead-lettered after MAX_CONSECUTIVE_DOCUMENT_FAILURES with a CRITICAL
        log, and the watermark advances the whole time — never frozen."""
        poison_id = 99

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            if doc["id"] == poison_id:
                raise RuntimeError(f"document {poison_id} is poison")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        # One store survives across every cycle so failed_documents and the
        # watermark persist — exactly the daemon's reuse pattern.
        store_writer = make_reconciler_store_writer()
        watermarks_seen: list[str | None] = []

        for cycle in range(MAX_CONSECUTIVE_DOCUMENT_FAILURES):
            # The healthy document's modified advances each cycle so the
            # watermark has somewhere new to move to.
            healthy = make_paperless_document(
                doc_id=1, modified=f"2024-06-{10 + cycle:02d}T00:00:00+00:00"
            )

            if cycle == 0:
                # Cycle 1: the poison document is in the watermark page.
                paperless = make_reconciler_paperless(
                    documents=[healthy, make_paperless_document(doc_id=poison_id)]
                )
            else:
                # Later cycles: the poison document is PAST the advanced
                # watermark — it must be re-fetched out-of-band via the
                # failed_documents retry path.
                paperless = make_reconciler_paperless(documents=[healthy])
                paperless.document_exists.return_value = True
                paperless.get_document.return_value = make_paperless_document(
                    doc_id=poison_id
                )

            watermarks_seen.append(store_writer.read_meta("modified_watermark"))

            reconciler = Reconciler(
                make_settings_obj(),
                paperless,
                store_writer,
                make_mock_embedding_client(),
            )
            # capture_logs intercepts structlog events as dicts regardless of
            # the configured renderer.
            with structlog.testing.capture_logs() as captured:
                report = reconciler.incremental_sync()

            if cycle == 0:
                # The poison doc was in the page so no out-of-band re-fetch.
                paperless.get_document.assert_not_called()
            else:
                # The poison doc lives past the watermark, so it is fetched
                # out-of-band via the failed-documents retry path.  (The healthy
                # page document is also re-fetched by the steady-state diff —
                # IDX-03 — since its modified advanced, so get_document is called
                # for both; assert the poison retry specifically happened.)
                poison_fetches = [
                    call
                    for call in paperless.get_document.call_args_list
                    if call.args == (poison_id,)
                ]
                assert len(poison_fetches) == 1

            if cycle < MAX_CONSECUTIVE_DOCUMENT_FAILURES - 1:
                # Still being retried — failed, not yet given up.
                assert report.failed == 1
                assert report.given_up == 0
                assert json.loads(store_writer._meta["failed_documents"]) == {
                    str(poison_id): cycle + 1
                }
                assert not [
                    e for e in captured if e["event"] == "reconcile.document_given_up"
                ]
            else:
                # The final cycle reaches the limit → dead-lettered.
                assert report.failed == 1
                assert report.given_up == 1
                assert str(poison_id) not in json.loads(
                    store_writer._meta["failed_documents"]
                )
                give_up_logs = [
                    e for e in captured if e["event"] == "reconcile.document_given_up"
                ]
                assert len(give_up_logs) == 1
                assert give_up_logs[0]["log_level"] == "critical"
                assert give_up_logs[0]["document_id"] == poison_id
                assert (
                    give_up_logs[0]["consecutive_failures"]
                    == MAX_CONSECUTIVE_DOCUMENT_FAILURES
                )

        # The watermark advanced on EVERY cycle — never frozen.  Each cycle saw
        # a strictly newer watermark (None on the first read).
        assert watermarks_seen[0] is None
        non_null = watermarks_seen[1:]
        assert non_null == sorted(non_null)
        assert len(set(non_null)) == len(non_null)  # strictly increasing

    def test_document_that_fails_once_then_succeeds_is_cleared_from_the_map(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transient failure is recorded, then cleared the cycle it succeeds."""
        flaky_id = 7
        attempts: dict[int, int] = {}

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            attempts[doc["id"]] = attempts.get(doc["id"], 0) + 1
            # The flaky document fails on its first attempt, succeeds after.
            if doc["id"] == flaky_id and attempts[doc["id"]] == 1:
                raise RuntimeError("transient embedding failure")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        store_writer = make_reconciler_store_writer()

        # Cycle 1: the flaky document is in the page and fails.
        paperless_one = make_reconciler_paperless(
            documents=[
                make_paperless_document(
                    doc_id=flaky_id, modified="2024-06-10T00:00:00+00:00"
                )
            ]
        )
        report_one = Reconciler(
            make_settings_obj(),
            paperless_one,
            store_writer,
            make_mock_embedding_client(),
        ).incremental_sync()

        assert report_one.failed == 1
        assert json.loads(store_writer._meta["failed_documents"]) == {str(flaky_id): 1}

        # Cycle 2: the watermark has advanced past the flaky document, so it is
        # re-fetched out-of-band — and this time it succeeds.
        paperless_two = make_reconciler_paperless(documents=[])
        paperless_two.document_exists.return_value = True
        paperless_two.get_document.return_value = make_paperless_document(
            doc_id=flaky_id, modified="2024-06-10T00:00:00+00:00"
        )
        report_two = Reconciler(
            make_settings_obj(),
            paperless_two,
            store_writer,
            make_mock_embedding_client(),
        ).incremental_sync()

        paperless_two.get_document.assert_called_once_with(flaky_id)
        assert report_two.indexed == 1
        assert report_two.failed == 0
        # Succeeded → cleared from the retry map entirely.
        assert json.loads(store_writer._meta["failed_documents"]) == {}

    def test_failed_document_deleted_from_paperless_is_dropped_from_the_map(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed document that 404s on re-fetch is dropped — the deletion
        sweep handles store cleanup, so it must not be retried forever."""
        gone_id = 13

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            if doc["id"] == gone_id:
                raise RuntimeError(f"document {doc['id']} failed")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        store_writer = make_reconciler_store_writer()

        # Cycle 1: the document is in the page and fails.
        paperless_one = make_reconciler_paperless(
            documents=[make_paperless_document(doc_id=gone_id)]
        )
        Reconciler(
            make_settings_obj(),
            paperless_one,
            store_writer,
            make_mock_embedding_client(),
        ).incremental_sync()
        assert json.loads(store_writer._meta["failed_documents"]) == {str(gone_id): 1}

        # Cycle 2: the document has been deleted from Paperless — document_exists
        # returns False, so the failed-document re-fetch must drop it.
        paperless_two = make_reconciler_paperless(documents=[])
        paperless_two.document_exists.return_value = False
        report = Reconciler(
            make_settings_obj(),
            paperless_two,
            store_writer,
            make_mock_embedding_client(),
        ).incremental_sync()

        # It was never fetched — document_exists said it was gone first.
        paperless_two.get_document.assert_not_called()
        # Dropped from the retry map; nothing failed this cycle.
        assert report.failed == 0
        assert json.loads(store_writer._meta["failed_documents"]) == {}

    def test_corrupt_failed_documents_meta_does_not_crash_the_cycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A malformed failed_documents meta value is dropped, not fatal."""
        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        store_writer = make_reconciler_store_writer()
        # Seed the meta with garbage that is not a JSON object of int counts.
        store_writer._meta["failed_documents"] = "{not valid json"

        paperless = make_reconciler_paperless(
            documents=[make_paperless_document(doc_id=1)]
        )
        report = Reconciler(
            make_settings_obj(),
            paperless,
            store_writer,
            make_mock_embedding_client(),
        ).incremental_sync()

        # The cycle completed and rewrote a clean (empty) map.
        assert report.indexed == 1
        assert json.loads(store_writer._meta["failed_documents"]) == {}
