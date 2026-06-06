"""Integration tests for the indexer reconciliation pipeline — deletion sweep.

These exercise the real :class:`~indexer.reconciler.Reconciler` and the real
:class:`~store.writer.StoreWriter` against a ``tmp_path`` SQLite store; only
Paperless and the embedding client are mocked.

Coverage here — the deletion sweep, SPEC §5.4:
- A complete enumeration prunes only the truly-absent documents.
- A successful but empty enumeration prunes every 404-confirmed document.
- A mid-pagination failure prunes NOTHING and leaves the store byte-for-byte
  intact (the data-loss prevention case).
- A candidate the per-id 404-confirm reports present survives.

The incremental-sync end-to-end coverage lives in test_indexer_pipeline.py —
the indexer pipeline tests are split across two files for the 500-line ceiling
(CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from indexer.reconciler import Reconciler
from tests.helpers.factories import make_paperless_document, make_store_settings
from tests.helpers.mocks import make_mock_embedding_client, make_reconciler_paperless
from tests.helpers.store import open_writer


def _settings(tmp_path: Any) -> MagicMock:
    """Return a store/indexer Settings mock pointed at the tmp_path store."""
    return make_store_settings(
        str(tmp_path / "index.db"), model="text-embedding-3-small"
    )


def _open_writer(tmp_path: Any) -> Any:
    """Open a real StoreWriter against the tmp_path index database."""
    return open_writer(str(tmp_path / "index.db"), model="text-embedding-3-small")


def _seed(store_writer: Any, tmp_path: Any, doc_ids: tuple[int, ...]) -> None:
    """Index *doc_ids* into the store via a real incremental sync cycle."""
    Reconciler(
        _settings(tmp_path),
        make_reconciler_paperless(
            documents=[make_paperless_document(doc_id=i) for i in doc_ids]
        ),
        store_writer,
        make_mock_embedding_client(),
    ).incremental_sync()


# ---------------------------------------------------------------------------
# Deletion sweep — end to end against a real store
# ---------------------------------------------------------------------------


class TestDeletionSweepEndToEnd:
    """The real sweep prunes a real store — safely."""

    def test_complete_enumeration_prunes_only_absent_documents(
        self, tmp_path: Any
    ) -> None:
        store_writer = _open_writer(tmp_path)
        try:
            _seed(store_writer, tmp_path, (1, 2, 3, 4))
            assert store_writer.get_all_document_ids() == {1, 2, 3, 4}

            # Paperless now only has 1 and 2 — documents 3 and 4 were deleted.
            report = Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(all_ids=[1, 2]),
                store_writer,
                make_mock_embedding_client(),
            ).deletion_sweep()

            assert report.aborted is False
            assert report.pruned == 2
            # Only the truly-absent documents are gone.
            assert store_writer.get_all_document_ids() == {1, 2}
        finally:
            store_writer.close()

    def test_empty_complete_enumeration_prunes_every_document(
        self, tmp_path: Any
    ) -> None:
        """The dangerous boundary, end to end: a SUCCESSFUL enumeration that
        yields zero ids while the store holds documents.

        ``iter_all_documents()`` completes normally returning ``[]`` — it does
        not raise — so the enumeration is authoritative, and every store
        document is 404-confirmed absent and pruned.
        """
        store_writer = _open_writer(tmp_path)
        try:
            _seed(store_writer, tmp_path, (1, 2, 3))
            assert store_writer.get_all_document_ids() == {1, 2, 3}

            # Paperless now has nothing — a successful, empty enumeration.
            report = Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(all_ids=[]),
                store_writer,
                make_mock_embedding_client(),
            ).deletion_sweep()

            assert report.aborted is False
            assert report.candidates == 3
            assert report.pruned == 3
            # The store is now empty — every document was correctly pruned.
            assert store_writer.get_all_document_ids() == set()
        finally:
            store_writer.close()

    def test_empty_enumeration_keeps_a_document_the_confirm_says_exists(
        self, tmp_path: Any
    ) -> None:
        """Empty enumeration, but one candidate's 404-confirm reports it PRESENT
        — that document survives.  The per-id confirm is the real guard."""
        store_writer = _open_writer(tmp_path)
        try:
            _seed(store_writer, tmp_path, (1, 2, 3))

            paperless_empty = make_reconciler_paperless(all_ids=[])
            # The enumeration listed nothing, but id 2 actually still exists.
            paperless_empty.document_exists.side_effect = lambda doc_id: doc_id == 2
            report = Reconciler(
                _settings(tmp_path),
                paperless_empty,
                store_writer,
                make_mock_embedding_client(),
            ).deletion_sweep()

            assert report.aborted is False
            assert report.pruned == 2
            # id 2 confirmed present → survives; 1 and 3 → pruned.
            assert store_writer.get_all_document_ids() == {2}
        finally:
            store_writer.close()

    def test_mid_pagination_failure_prunes_nothing_and_leaves_store_intact(
        self, tmp_path: Any
    ) -> None:
        """THE data-loss prevention case, end to end.

        If the enumeration raises mid-pagination, the sweep aborts and the
        store is left byte-for-byte unchanged — not one document is pruned.
        """
        store_writer = _open_writer(tmp_path)
        try:
            _seed(store_writer, tmp_path, (1, 2, 3, 4, 5))
            before = store_writer.get_all_document_ids()
            assert before == {1, 2, 3, 4, 5}

            # The sweep's enumeration fails after two pages — a network drop.
            paperless_broken = MagicMock()

            def _iter_all_documents(
                *,
                modified_after: str | None = None,
                fields: tuple[str, ...] | None = None,
            ):
                yield {"id": 1}
                yield {"id": 2}
                raise ConnectionError("Paperless vanished mid-pagination")

            paperless_broken.iter_all_documents.side_effect = _iter_all_documents

            report = Reconciler(
                _settings(tmp_path),
                paperless_broken,
                store_writer,
                make_mock_embedding_client(),
            ).deletion_sweep()

            assert report.aborted is True
            assert report.pruned == 0
            # The store is completely untouched — no false prune.
            assert store_writer.get_all_document_ids() == before
        finally:
            store_writer.close()

    def test_candidate_confirmed_present_is_not_pruned(self, tmp_path: Any) -> None:
        """A document missing from the page list but confirmed present is kept."""
        store_writer = _open_writer(tmp_path)
        try:
            _seed(store_writer, tmp_path, (1, 2, 3))

            # Enumeration lists only id 1, but the per-id confirmation says
            # id 2 still exists (a race) and id 3 is genuinely gone.
            paperless_sweep = make_reconciler_paperless(all_ids=[1])
            paperless_sweep.document_exists.side_effect = lambda doc_id: doc_id == 2
            report = Reconciler(
                _settings(tmp_path),
                paperless_sweep,
                store_writer,
                make_mock_embedding_client(),
            ).deletion_sweep()

            assert report.pruned == 1
            # id 2 was confirmed present → kept; id 3 → pruned.
            assert store_writer.get_all_document_ids() == {1, 2}
        finally:
            store_writer.close()
