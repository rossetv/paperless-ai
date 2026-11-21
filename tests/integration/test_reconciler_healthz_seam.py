"""Integration tests for the reconciler → healthz seam.

A real ``incremental_sync`` must write ``last_reconcile_at`` to the store so
healthz reports ready; other healthz tests seed that value by hand.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from indexer.reconciler import Reconciler
from indexer.worker import IndexOutcome
from store.reader import StoreReader
from store.writer import StoreWriter
from tests.helpers.factories import make_search_settings

_DIMENSIONS = 4


def _make_settings(tmp_path: Path) -> MagicMock:
    """Return search settings for the tmp_path store, plus ``DOCUMENT_WORKERS``."""
    return make_search_settings(
        INDEX_DB_PATH=str(tmp_path / "index.db"),
        EMBEDDING_DIMENSIONS=_DIMENSIONS,
        PAPERLESS_URL="http://paperless.test",
        DOCUMENT_WORKERS=1,
    )


def _make_paperless_empty() -> MagicMock:
    """A Paperless client that reports zero documents (empty index)."""
    paperless = MagicMock()
    paperless.iter_all_documents.return_value = []
    paperless.list_correspondents.return_value = []
    paperless.list_document_types.return_value = []
    paperless.list_tags.return_value = []
    return paperless


def _make_embedding_client() -> MagicMock:
    return MagicMock()


class TestReconcilerHealthzSeam:
    """The real Reconciler.incremental_sync() must make healthz report ready."""

    def test_healthz_reports_ready_after_real_incremental_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a real reconcile the store reports ``last_reconcile_at``."""
        settings = _make_settings(tmp_path)

        store_writer = StoreWriter(settings)

        # Paperless returns no documents, so the worker should never run; stub it
        # anyway as a safety net.
        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        reconciler = Reconciler(
            settings,
            _make_paperless_empty(),
            store_writer,
            _make_embedding_client(),
        )
        reconciler.incremental_sync()
        store_writer.close()

        store_reader = StoreReader(settings)
        try:
            stats = store_reader.get_stats()
            assert stats.last_reconcile_at is not None, (
                "last_reconcile_at was not written by incremental_sync(); "
                "the search server would return 503 index-not-ready forever"
            )
        finally:
            store_reader.close()

    def test_healthz_endpoint_returns_200_after_real_incremental_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /api/healthz returns 200, not 503, after a real reconcile."""
        from search.api import create_app

        settings = _make_settings(tmp_path)

        store_writer = StoreWriter(settings)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        reconciler = Reconciler(
            settings,
            _make_paperless_empty(),
            store_writer,
            _make_embedding_client(),
        )
        reconciler.incremental_sync()
        store_writer.close()

        store_reader = StoreReader(settings)
        try:
            core_stub = MagicMock()
            app = create_app(settings, core=core_stub, store_reader=store_reader)
            client = TestClient(app, raise_server_exceptions=False)

            response = client.get("/api/healthz")

            assert response.status_code == 200, (
                f"Expected 200 ok but got {response.status_code}: {response.json()!r}. "
                "Check that Reconciler.incremental_sync() writes last_reconcile_at."
            )
            assert response.json()["status"] == "ok"
        finally:
            store_reader.close()
