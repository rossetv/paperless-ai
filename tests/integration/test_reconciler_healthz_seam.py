"""Integration test for the reconciler → healthz seam.

This test closes the gap exposed in the whole-branch review: the existing
integration test for ``/api/healthz`` faked the ``last_reconcile_at`` write
directly in ``_seed_store`` (calling ``writer.write_meta("last_reconcile_at",
...)`` by hand), which meant the real production code path — the Reconciler
writing it at the end of ``incremental_sync`` — was never exercised.

This test:
1. Creates a real SQLite store in ``tmp_path`` via ``StoreWriter``.
2. Runs the REAL ``Reconciler.incremental_sync()`` against that store.
3. Opens the SAME store via ``StoreReader`` and calls the REAL healthz
   logic (``store_reader.get_stats()`` → check ``last_reconcile_at``).
4. Asserts the result is **ready (200 ok)**, not 503.

The test is designed to fail if the ``last_reconcile_at`` write is removed
from ``incremental_sync()``: without that write ``get_stats()`` returns
``None`` for ``last_reconcile_at``, and healthz would return 503.
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

# ---------------------------------------------------------------------------
# Test-local helpers
# ---------------------------------------------------------------------------

_DIMENSIONS = 4


def _make_settings(tmp_path: Path) -> MagicMock:
    """Return a settings mock pointing at the tmp_path store.

    Routed through the shared :func:`~tests.helpers.factories.make_search_settings`
    factory; only the reconciler-specific ``DOCUMENT_WORKERS`` is added on top.
    """
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


# ---------------------------------------------------------------------------
# The seam test
# ---------------------------------------------------------------------------


class TestReconcilerHealthzSeam:
    """The real Reconciler.incremental_sync() must make healthz report ready."""

    def test_healthz_reports_ready_after_real_incremental_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After running the REAL reconciler against a REAL store, the REAL
        healthz handler must return 200 ok, not 503 index-not-ready.

        This test WILL fail if ``last_reconcile_at`` is not written by
        ``incremental_sync()``: without that write ``StoreReader.get_stats()``
        returns ``last_reconcile_at=None``, and ``/api/healthz`` returns 503.
        """
        settings = _make_settings(tmp_path)

        # Step 1: initialise the real store (creates the schema).
        store_writer = StoreWriter(settings)

        # Step 2: stub out DocumentIndexer.index_document — there are no
        # real documents in this cycle (Paperless returns empty), so the
        # worker is never called.  The stub is here as a safety net.
        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        # Step 3: run the REAL reconciler against the REAL store.
        reconciler = Reconciler(
            settings,
            _make_paperless_empty(),
            store_writer,
            _make_embedding_client(),
        )
        reconciler.incremental_sync()
        store_writer.close()

        # Step 4: open the SAME store via the REAL StoreReader and check
        # the healthz logic directly.
        store_reader = StoreReader(settings)
        try:
            stats = store_reader.get_stats()
            # The reconciler must have written last_reconcile_at.
            assert stats.last_reconcile_at is not None, (
                "last_reconcile_at was not written by incremental_sync(); "
                "the search server would return 503 index-not-ready forever"
            )
        finally:
            store_reader.close()

    def test_healthz_endpoint_returns_200_after_real_incremental_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The full HTTP healthz endpoint must return 200 after a real reconcile.

        This exercises the complete path: StoreWriter (indexer) → incremental_sync
        → SQLite meta → StoreReader.get_stats → FastAPI /api/healthz → 200.

        Revert the last_reconcile_at write in reconciler.incremental_sync() and
        this test returns 503 {"status": "index-not-ready"} instead of 200.
        """
        from search.api import create_app

        settings = _make_settings(tmp_path)

        # Initialise the store and run a real reconcile cycle.
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

        # Open the SAME store for the search server.
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
