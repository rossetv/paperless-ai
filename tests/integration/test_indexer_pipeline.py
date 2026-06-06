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
                make_paperless_document(doc_id=1, modified="2024-06-01T00:00:00+00:00"),
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

    def test_metadata_change_refetches_as_metadata_only(self, tmp_path: Any) -> None:
        """A classifier metadata PATCH advances ``modified``; the second cycle
        re-fetches the document and the content-hash gate makes it a cheap
        METADATA_ONLY update — no re-embed.

        Paperless bumps ``modified`` on every save (auto_now), so a title/tag
        change advances it: the steady-state diff (IDX-03) therefore re-fetches
        the document and runs the SHA-256 gate, which routes the byte-identical
        OCR content to ``update_metadata``.  (An *unchanged* ``modified`` is
        skipped cold instead — covered by
        ``TestSteadyStateLightDiffEndToEnd``.)
        """
        store_writer = _open_writer(tmp_path)
        try:
            content = "Boundary document — stable content."

            # Cycle 1: index the document fresh.
            Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(
                    documents=[
                        make_paperless_document(
                            doc_id=5,
                            content=content,
                            modified="2024-06-05T12:00:00+00:00",
                            title="Original Title",
                        )
                    ]
                ),
                store_writer,
                make_mock_embedding_client(),
            ).incremental_sync()

            # Cycle 2: a classifier metadata PATCH changed the title and so
            # advanced modified; the OCR content is byte-identical.
            embedding_two = make_mock_embedding_client()
            report_two = Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(
                    documents=[
                        make_paperless_document(
                            doc_id=5,
                            content=content,
                            modified="2024-06-06T09:30:00+00:00",
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

    def test_emptied_content_prunes_the_previously_indexed_document(
        self, tmp_path: Any
    ) -> None:
        """A document whose OCR content is cleared after indexing is pruned.

        IDX-01: cycle 1 indexes a document with content; cycle 2 re-enters it
        with the content cleared (and ``modified`` advanced, as Paperless bumps
        it on every save).  The worker must delete its stale rows from the real
        store so search stops serving chunks for content that no longer exists.
        Before the fix the document survived as a SKIPPED no-op and its chunks
        lingered.
        """
        store_writer = _open_writer(tmp_path)
        try:
            # Cycle 1: index a real document with content.
            Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(
                    documents=[
                        make_paperless_document(
                            doc_id=42,
                            content="Content that will later be cleared.",
                            modified="2024-06-01T00:00:00+00:00",
                        )
                    ]
                ),
                store_writer,
                make_mock_embedding_client(),
            ).incremental_sync()
            assert 42 in store_writer.get_all_document_ids()

            # Cycle 2: the OCR content is cleared (e.g. the source file was
            # replaced and re-OCR is pending); ``modified`` advanced.
            report = Reconciler(
                _settings(tmp_path),
                make_reconciler_paperless(
                    documents=[
                        make_paperless_document(
                            doc_id=42,
                            content="",
                            modified="2024-07-01T00:00:00+00:00",
                        )
                    ]
                ),
                store_writer,
                make_mock_embedding_client(),
            ).incremental_sync()

            assert report.skipped == 1
            assert report.indexed == 0
            # The stale rows are gone from the real store.
            assert 42 not in store_writer.get_all_document_ids()
            assert 42 not in store_writer.get_index_state()
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
# Steady-state light-diff (IDX-03) — end to end against a real store
# ---------------------------------------------------------------------------


class TestSteadyStateLightDiffEndToEnd:
    """The IDX-03 steady-state skip, against a real store and real worker."""

    def test_unchanged_reentry_skips_without_refetching_content(
        self, tmp_path: Any
    ) -> None:
        """Cycle 1 indexes a doc; cycle 2 (overlap re-entry) skips it cold.

        Cycle 2 pages the light {id, modified} projection. Because the store now
        holds the doc's normalised modified, the reconciler skips it WITHOUT
        calling get_document — proving no OCR body is re-fetched (IDX-03) and the
        document is not re-embedded (the SHA-256 gate is never even reached
        because nothing changed).
        """
        from common.clock import normalise_paperless_timestamp

        content = "--- Page 1 ---\nStable invoice body for the steady-state test."
        modified = "2024-06-01T12:00:00+00:00"
        full_doc = make_paperless_document(
            doc_id=42, content=content, modified=modified
        )

        # A Paperless mock that serves full docs on cycle 1 (first run, no
        # fields) and the light projection on cycle 2 (fields requested).
        paperless = MagicMock()
        light_row = {"id": 42, "modified": modified}

        def _iter(**kwargs: Any) -> list[dict]:
            if "modified_after" not in kwargs:
                return [{"id": 42}]  # sweep-style (unused here)
            if kwargs.get("fields") is not None:
                return [light_row]
            return [full_doc]

        paperless.iter_all_documents.side_effect = _iter
        paperless.get_document.side_effect = lambda doc_id: full_doc
        paperless.list_correspondents.return_value = []
        paperless.list_document_types.return_value = []
        paperless.list_tags.return_value = []

        embedding_client = make_mock_embedding_client()
        writer = _open_writer(tmp_path)
        try:
            reconciler = Reconciler(
                _settings(tmp_path),
                paperless,
                writer,
                embedding_client,
            )

            # Cycle 1: first run (no watermark) → full document path → indexed.
            report1 = reconciler.incremental_sync()
            assert report1.indexed == 1
            embed_calls_after_cycle1 = embedding_client.embed.call_count
            assert embed_calls_after_cycle1 >= 1

            # The store now holds doc 42 with the normalised modified.
            state = writer.get_index_state()
            assert 42 in state
            assert state[42].modified == normalise_paperless_timestamp(modified)

            # Cycle 2: a watermark exists → light projection. The doc re-enters
            # via the overlap but is byte-for-byte unchanged → skipped cold.
            paperless.get_document.reset_mock()
            report2 = reconciler.incremental_sync()

            assert report2.indexed == 0
            assert report2.metadata_only == 0
            # No OCR body re-fetched (the IDX-03 win).
            paperless.get_document.assert_not_called()
            # No re-embed (the SHA-256 incremental guarantee).
            assert embedding_client.embed.call_count == embed_calls_after_cycle1
        finally:
            writer.close()


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
