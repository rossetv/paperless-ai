"""Integration tests for the indexer reconciliation pipeline — sync path.

These exercise the real :class:`~indexer.reconciler.Reconciler` and the real
:class:`~store.writer.StoreWriter` against a ``tmp_path`` SQLite store.  Only
Paperless and the embedding client are mocked — the reconciler, the worker, the
chunker, and every store transaction are exercised for real.

Coverage here:
- A first incremental sync indexes new documents into the store and advances
  the watermark; a second cycle with the overlap re-includes the boundary
  document as a cheap metadata-only no-op.
- A changed document is re-indexed end-to-end.
- A taxonomy rename in Paperless propagates into the store's taxonomy table.
- A single failing document is isolated; the rest of the cycle still commits.

The deletion-sweep end-to-end coverage lives in test_indexer_pipeline_sweep.py
— the indexer pipeline tests are split across two files for the 500-line
ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from indexer.reconciler import OVERLAP_MARGIN, Reconciler
from tests.helpers.factories import make_paperless_document
from tests.helpers.mocks import make_mock_embedding_client, make_reconciler_paperless
from tests.helpers.store import open_reader, open_writer


# ---------------------------------------------------------------------------
# Test-local helpers
# ---------------------------------------------------------------------------


def _settings(tmp_path: Any) -> MagicMock:
    """Return a store/indexer Settings mock pointed at the tmp_path store."""
    from tests.helpers.factories import make_store_settings

    return make_store_settings(
        str(tmp_path / "index.db"), model="text-embedding-3-small"
    )


def _open_writer(tmp_path: Any) -> Any:
    """Open a real StoreWriter against the tmp_path index database."""
    return open_writer(str(tmp_path / "index.db"), model="text-embedding-3-small")


# ---------------------------------------------------------------------------
# Incremental sync — end to end against a real store
# ---------------------------------------------------------------------------


class TestIncrementalSyncEndToEnd:
    """The real reconciler indexes documents into a real store."""

    def test_new_documents_land_in_the_store_and_watermark_advances(
        self, tmp_path: Any
    ) -> None:
        store_writer = _open_writer(tmp_path)
        try:
            latest = "2024-06-10T09:00:00+00:00"
            docs = [
                make_paperless_document(
                    doc_id=1, modified="2024-06-01T00:00:00+00:00"
                ),
                make_paperless_document(doc_id=2, modified=latest),
            ]
            report = Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(documents=docs),
                store_writer,
                make_mock_embedding_client(),
            ).incremental_sync()

            assert report.indexed == 2
            assert store_writer.get_all_document_ids() == {1, 2}

            # Watermark advanced to max(modified) - OVERLAP_MARGIN.
            expected = (datetime.fromisoformat(latest) - OVERLAP_MARGIN).isoformat()
            assert store_writer.read_meta("modified_watermark") == expected
        finally:
            store_writer.close()

    def test_overlap_reincludes_boundary_document_as_metadata_only(
        self, tmp_path: Any
    ) -> None:
        """A second cycle re-fetches the boundary document; the content-hash
        gate makes it a cheap METADATA_ONLY update — no re-embed."""
        store_writer = _open_writer(tmp_path)
        try:
            content = "Boundary document — stable content."
            modified = "2024-06-05T12:00:00+00:00"

            # Cycle 1: index the document fresh.
            Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(
                    documents=[
                        make_paperless_document(
                            doc_id=5,
                            content=content,
                            modified=modified,
                            title="Original Title",
                        )
                    ]
                ),
                store_writer,
                make_mock_embedding_client(),
            ).incremental_sync()

            # Cycle 2: the watermark overlap re-fetches the same document, but
            # only its title has changed — the OCR content is byte-identical.
            embedding_two = make_mock_embedding_client()
            report_two = Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(
                    documents=[
                        make_paperless_document(
                            doc_id=5,
                            content=content,
                            modified=modified,
                            title="Title Updated By The Classifier",
                        )
                    ]
                ),
                store_writer,
                embedding_two,
            ).incremental_sync()

            # The hash gate fired: a metadata-only update, no embedding call.
            assert report_two.metadata_only == 1
            assert report_two.indexed == 0
            embedding_two.embed.assert_not_called()
        finally:
            store_writer.close()

    def test_changed_document_is_reindexed(self, tmp_path: Any) -> None:
        """A document whose OCR content changes is re-chunked and re-embedded."""
        store_writer = _open_writer(tmp_path)
        try:
            Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(
                    documents=[
                        make_paperless_document(
                            doc_id=8, content="The original OCR content."
                        )
                    ]
                ),
                store_writer,
                make_mock_embedding_client(),
            ).incremental_sync()

            original_state = store_writer.get_index_state()[8]

            # The document's content genuinely changes.
            changed = make_paperless_document(
                doc_id=8,
                content="Completely rewritten OCR content body.",
                modified="2024-07-01T00:00:00+00:00",
            )
            embedding_two = make_mock_embedding_client()
            report = Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(documents=[changed]),
                store_writer,
                embedding_two,
            ).incremental_sync()

            assert report.indexed == 1
            embedding_two.embed.assert_called_once()

            # The stored content hash moved on.
            new_state = store_writer.get_index_state()[8]
            assert new_state.content_hash != original_state.content_hash
            expected_hash = hashlib.sha256(changed["content"].encode()).hexdigest()
            assert new_state.content_hash == expected_hash
        finally:
            store_writer.close()

    def test_partial_incremental_enumeration_leaves_watermark_unmoved(
        self, tmp_path: Any
    ) -> None:
        """A mid-pagination failure during incremental sync, end to end.

        The incremental page generator yields one document then raises.  The
        failure propagates out of incremental_sync (the daemon cycle boundary
        catches it), and the real store's modified_watermark must be exactly
        what it was — a partial page is never authoritative.
        """
        store_writer = _open_writer(tmp_path)
        try:
            # Seed the store via a clean first cycle so a real watermark exists.
            Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(
                    documents=[
                        make_paperless_document(
                            doc_id=1, modified="2024-06-01T00:00:00+00:00"
                        )
                    ]
                ),
                store_writer,
                make_mock_embedding_client(),
            ).incremental_sync()
            watermark_before = store_writer.read_meta("modified_watermark")
            assert watermark_before is not None

            # The next cycle's incremental enumeration fails mid-pagination.
            paperless_broken = MagicMock()

            def _iter_all_documents(**kwargs: Any):
                yield make_paperless_document(
                    doc_id=2, modified="2024-07-01T00:00:00+00:00"
                )
                raise ConnectionError("Paperless vanished mid-incremental-page")

            paperless_broken.iter_all_documents.side_effect = _iter_all_documents
            paperless_broken.list_correspondents.return_value = []
            paperless_broken.list_document_types.return_value = []
            paperless_broken.list_tags.return_value = []

            with pytest.raises(ConnectionError):
                Reconciler(
                    _settings(tmp_path),
                    paperless_broken,
                    store_writer,
                    make_mock_embedding_client(),
                ).incremental_sync()

            # The watermark is byte-for-byte unchanged.
            assert store_writer.read_meta("modified_watermark") == watermark_before
        finally:
            store_writer.close()


# ---------------------------------------------------------------------------
# Taxonomy refresh — end to end
# ---------------------------------------------------------------------------


class TestTaxonomyRefreshEndToEnd:
    """A correspondent rename in Paperless propagates into the store."""

    def test_renamed_correspondent_propagates_into_the_store(
        self, tmp_path: Any
    ) -> None:
        store_writer = _open_writer(tmp_path)
        try:
            doc = make_paperless_document(doc_id=1, correspondent=99)

            # Cycle 1: Paperless reports the correspondent under its old name.
            Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(
                    documents=[doc],
                    correspondents=[{"id": 99, "name": "Old Energy Co"}],
                ),
                store_writer,
                make_mock_embedding_client(),
            ).incremental_sync()

            assert _correspondent_name(tmp_path, 99) == "Old Energy Co"

            # Cycle 2: the correspondent has been renamed in Paperless.
            Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(
                    documents=[doc],
                    correspondents=[{"id": 99, "name": "New Energy Co Ltd"}],
                ),
                store_writer,
                make_mock_embedding_client(),
            ).incremental_sync()

            # The taxonomy row now carries the new name — no document rewrite.
            assert _correspondent_name(tmp_path, 99) == "New Energy Co Ltd"
        finally:
            store_writer.close()


def _correspondent_name(tmp_path: Any, correspondent_id: int) -> str:
    """Read a correspondent's name back through the store's typed read API.

    Opens a StoreReader on the same store and uses ``get_taxonomy`` — the
    typed taxonomy-read method — rather than reaching into a writer's private
    connection.  This exercises a real public read path end to end.
    """
    reader = open_reader(str(tmp_path / "index.db"))
    try:
        entry = next(
            entry
            for entry in reader.get_taxonomy("correspondent")
            if entry.id == correspondent_id
        )
    finally:
        reader.close()
    return entry.name


# ---------------------------------------------------------------------------
# Per-document failure isolation — end to end
# ---------------------------------------------------------------------------


class TestFailureIsolationEndToEnd:
    """A single failing document does not stop the rest of the cycle."""

    def test_one_failing_document_isolated_others_still_committed(
        self, tmp_path: Any
    ) -> None:
        store_writer = _open_writer(tmp_path)
        try:
            docs = [make_paperless_document(doc_id=i) for i in (1, 2, 3)]

            # Make the embedding client explode for the second document it sees.
            # The reconciler must catch it, count it, and carry on with 1 and 3.
            embedding_client = MagicMock()
            real_vectors = [[0.5, 0.5, 0.5, 0.5]]

            def _embed(texts: list[str]) -> list[list[float]]:
                # The three docs share content, so fail on the 2nd embed call.
                _embed.calls += 1  # type: ignore[attr-defined]
                if _embed.calls == 2:  # type: ignore[attr-defined]
                    raise RuntimeError("embedding API failed for one document")
                return real_vectors * len(texts)

            _embed.calls = 0  # type: ignore[attr-defined]
            embedding_client.embed.side_effect = _embed

            report = Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(documents=docs),
                store_writer,
                embedding_client,
            ).incremental_sync()

            # Exactly one document failed; the other two committed.
            assert report.failed == 1
            assert report.indexed == 2
            assert len(store_writer.get_all_document_ids()) == 2
        finally:
            store_writer.close()
