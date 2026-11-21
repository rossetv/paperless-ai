"""Tests for the reconciler's bounded failed-document retry.

The watermark advances regardless of failures; failed documents are tracked in
the persisted ``failed_documents`` map, retried out-of-band each cycle, and
dead-lettered after ``MAX_CONSECUTIVE_DOCUMENT_FAILURES`` consecutive failures.
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
        """The watermark advances to ``max(modified) - OVERLAP`` despite a failure."""
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
        expected = (datetime.fromisoformat(latest) - OVERLAP_MARGIN).isoformat()
        assert store_writer._meta["modified_watermark"] == expected
        assert json.loads(store_writer._meta["failed_documents"]) == {"2": 1}

    def test_permanently_failing_document_is_retried_then_dead_lettered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dead-lettering logs CRITICAL, and the watermark advances every cycle."""
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

        # One store across every cycle, as the daemon reuses it, so
        # failed_documents and the watermark persist.
        store_writer = make_reconciler_store_writer()
        watermarks_seen: list[str | None] = []

        for cycle in range(MAX_CONSECUTIVE_DOCUMENT_FAILURES):
            # Gives the watermark somewhere new to move to each cycle.
            healthy = make_paperless_document(
                doc_id=1, modified=f"2024-06-{10 + cycle:02d}T00:00:00+00:00"
            )

            if cycle == 0:
                paperless = make_reconciler_paperless(
                    documents=[healthy, make_paperless_document(doc_id=poison_id)]
                )
            else:
                # The poison document is now behind the advanced watermark, so
                # only the failed_documents retry path can re-fetch it.
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
            with structlog.testing.capture_logs() as captured:
                report = reconciler.incremental_sync()

            if cycle == 0:
                paperless.get_document.assert_not_called()
            else:
                # The healthy document is re-fetched too (its modified
                # advanced), so count only the poison document's fetches.
                poison_fetches = [
                    call
                    for call in paperless.get_document.call_args_list
                    if call.args == (poison_id,)
                ]
                assert len(poison_fetches) == 1

            if cycle < MAX_CONSECUTIVE_DOCUMENT_FAILURES - 1:
                assert report.failed == 1
                assert report.given_up == 0
                assert json.loads(store_writer._meta["failed_documents"]) == {
                    str(poison_id): cycle + 1
                }
                assert not [
                    e for e in captured if e["event"] == "reconcile.document_given_up"
                ]
            else:
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

        assert watermarks_seen[0] is None
        non_null = watermarks_seen[1:]
        assert non_null == sorted(non_null)
        assert len(set(non_null)) == len(non_null)  # strictly increasing

    def test_document_that_fails_once_then_succeeds_is_cleared_from_the_map(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        flaky_id = 7
        attempts: dict[int, int] = {}

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            attempts[doc["id"]] = attempts.get(doc["id"], 0) + 1
            if doc["id"] == flaky_id and attempts[doc["id"]] == 1:
                raise RuntimeError("transient embedding failure")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        store_writer = make_reconciler_store_writer()

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

        # The watermark has moved past the flaky document, so it is re-fetched
        # out-of-band.
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
        assert json.loads(store_writer._meta["failed_documents"]) == {}

    def test_failed_document_deleted_from_paperless_is_dropped_from_the_map(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The deletion sweep cleans the store, so a vanished document is not
        retried forever."""
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

        paperless_two = make_reconciler_paperless(documents=[])
        paperless_two.document_exists.return_value = False
        report = Reconciler(
            make_settings_obj(),
            paperless_two,
            store_writer,
            make_mock_embedding_client(),
        ).incremental_sync()

        paperless_two.get_document.assert_not_called()
        assert report.failed == 0
        assert json.loads(store_writer._meta["failed_documents"]) == {}

    def test_corrupt_failed_documents_meta_does_not_crash_the_cycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        store_writer = make_reconciler_store_writer()
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

        assert report.indexed == 1
        assert json.loads(store_writer._meta["failed_documents"]) == {}
