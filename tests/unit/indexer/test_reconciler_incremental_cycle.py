"""Tests for indexer.reconciler incremental sync — per-cycle bookkeeping.

Each ``incremental_sync`` cycle does more than index documents:
- It refreshes the taxonomy every cycle, so a Paperless rename propagates even
  on a cycle that indexes nothing (SPEC §5.5).
- It writes ``last_reconcile_at`` at the end of every completed cycle, so
  ``/api/healthz`` can report the index as ready (SPEC §4.1).
- It returns a frozen :class:`~indexer.reconciler.SyncReport`.

The watermark-driven core lives in test_reconciler_incremental.py; the bounded
failed-document retry in test_reconciler_failed_documents.py — the reconciler's
tests are split across files to stay under the 500-line ceiling
(CODE_GUIDELINES §3.1, §11.2).  The Paperless and StoreWriter mock builders,
``always_indexed``, and ``run_incremental_sync`` come from
tests/unit/indexer/conftest.py.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from indexer.reconciler import OVERLAP_MARGIN, SyncReport
from indexer.worker import IndexOutcome
from store.models import IndexState
from tests.helpers.factories import make_paperless_document
from tests.unit.indexer.conftest import (
    always_indexed,
    make_reconciler_paperless,
    make_reconciler_store_writer,
    run_incremental_sync,
)


# ---------------------------------------------------------------------------
# incremental_sync — taxonomy refresh every cycle
# ---------------------------------------------------------------------------


class TestIncrementalSyncRefreshesTaxonomy:
    """Every cycle rebuilds the taxonomy so a Paperless rename propagates."""

    def test_taxonomy_is_refreshed_with_correspondents_types_and_tags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paperless = make_reconciler_paperless(documents=[])
        paperless.list_correspondents.return_value = [{"id": 1, "name": "npower"}]
        paperless.list_document_types.return_value = [{"id": 2, "name": "Invoice"}]
        paperless.list_tags.return_value = [{"id": 3, "name": "urgent"}]
        store_writer = make_reconciler_store_writer()

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        store_writer.refresh_taxonomy.assert_called_once()
        entries = list(store_writer.refresh_taxonomy.call_args[0][0])
        kinds = {(entry.kind, entry.id, entry.name) for entry in entries}
        assert ("correspondent", 1, "npower") in kinds
        assert ("document_type", 2, "Invoice") in kinds
        assert ("tag", 3, "urgent") in kinds

    def test_renamed_correspondent_propagates_into_the_refresh(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The name from Paperless is what reaches refresh_taxonomy verbatim."""
        paperless = make_reconciler_paperless(documents=[])
        paperless.list_correspondents.return_value = [
            {"id": 42, "name": "Npower Renamed Ltd"}
        ]
        store_writer = make_reconciler_store_writer()

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        entries = list(store_writer.refresh_taxonomy.call_args[0][0])
        correspondent = next(e for e in entries if e.kind == "correspondent")
        assert correspondent.id == 42
        assert correspondent.name == "Npower Renamed Ltd"

    def test_taxonomy_refreshed_once_not_per_document(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The taxonomy maps are built once per cycle, not per document (§14.5)."""
        docs = [make_paperless_document(doc_id=i) for i in range(1, 6)]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer()

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        assert store_writer.refresh_taxonomy.call_count == 1
        assert paperless.list_correspondents.call_count == 1
        assert paperless.list_document_types.call_count == 1
        assert paperless.list_tags.call_count == 1


# ---------------------------------------------------------------------------
# incremental_sync — last_reconcile_at is written every completed cycle
# ---------------------------------------------------------------------------


class TestIncrementalSyncWritesLastReconcileAt:
    """``incremental_sync`` writes ``last_reconcile_at`` at the end of every
    completed cycle so that ``/api/healthz`` can report the index as ready.

    Regression: the reconciler previously wrote ``modified_watermark``,
    ``last_full_sweep_at``, and ``failed_documents`` but never
    ``last_reconcile_at``, so the search server returned 503 index-not-ready
    for its entire lifetime.
    """

    def test_last_reconcile_at_is_set_after_a_cycle_with_documents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A normal cycle that indexes documents must set last_reconcile_at."""
        paperless = make_reconciler_paperless(
            documents=[make_paperless_document(doc_id=1)]
        )
        store_writer = make_reconciler_store_writer()
        assert "last_reconcile_at" not in store_writer._meta

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        assert store_writer._meta.get("last_reconcile_at") is not None

    def test_last_reconcile_at_is_set_after_an_empty_cycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty cycle must still set last_reconcile_at — an empty-but-
        reconciled index is genuinely ready."""
        paperless = make_reconciler_paperless(documents=[])
        store_writer = make_reconciler_store_writer()
        assert "last_reconcile_at" not in store_writer._meta

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        assert store_writer._meta.get("last_reconcile_at") is not None

    def test_last_reconcile_at_is_set_even_when_some_documents_fail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Per-document failures are isolated; the cycle still completes and
        must write last_reconcile_at (SPEC §5.7)."""
        docs = [make_paperless_document(doc_id=i) for i in (1, 2)]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer()
        assert "last_reconcile_at" not in store_writer._meta

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            if doc["id"] == 1:
                raise RuntimeError("doc 1 failed")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert report.failed == 1
        # The cycle completed despite the failure — last_reconcile_at must be set.
        assert store_writer._meta.get("last_reconcile_at") is not None


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------


class TestSyncReportShape:
    """SyncReport is a frozen dataclass and OVERLAP_MARGIN is a short delta."""

    def test_sync_report_is_frozen(self) -> None:
        report = SyncReport(indexed=1, metadata_only=0, skipped=0, failed=0, given_up=0)
        with pytest.raises(FrozenInstanceError):
            report.indexed = 99  # type: ignore[misc]

    def test_overlap_margin_is_a_short_timedelta(self) -> None:
        """OVERLAP_MARGIN is a few seconds — long enough to absorb a boundary
        race, short enough that re-processing is trivial."""
        assert isinstance(OVERLAP_MARGIN, timedelta)
        assert timedelta(0) < OVERLAP_MARGIN <= timedelta(minutes=1)
