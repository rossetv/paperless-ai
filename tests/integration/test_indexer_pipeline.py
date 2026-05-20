"""Integration tests for the indexer reconciliation pipeline.

These exercise the real :class:`~indexer.reconciler.Reconciler` and the real
:class:`~store.writer.StoreWriter` against a ``tmp_path`` SQLite store.  Only
Paperless and the embedding client are mocked — the reconciler, the worker,
the chunker, and every store transaction are exercised for real.

Coverage:
- A first incremental sync indexes new documents into the store and advances
  the watermark; a second cycle with the overlap re-includes the boundary
  document as a cheap metadata-only no-op.
- A changed document is re-indexed end-to-end.
- A taxonomy rename in Paperless propagates into the store's taxonomy table.
- A deletion sweep with a complete enumeration prunes only the truly-absent
  documents; a mid-pagination failure prunes NOTHING and leaves the store
  byte-for-byte intact.
- A single failing document is isolated; the rest of the cycle still commits.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from indexer.reconciler import OVERLAP_MARGIN, Reconciler
from store.writer import StoreWriter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Any, *, document_workers: int = 2) -> MagicMock:
    """Return a settings mock the reconciler, worker, and store all read."""
    settings = MagicMock()
    settings.INDEX_DB_PATH = str(tmp_path / "index.db")
    settings.EMBEDDING_MODEL = "text-embedding-3-small"
    settings.EMBEDDING_DIMENSIONS = 4
    settings.DOCUMENT_WORKERS = document_workers
    settings.CHUNK_SIZE = 2000
    settings.CHUNK_OVERLAP = 256
    settings.ERROR_TAG_ID = 552
    return settings


def _make_embedding_client(dimensions: int = 4) -> MagicMock:
    """A mock EmbeddingClient whose embed() returns deterministic vectors."""
    client = MagicMock()
    client.embed.side_effect = lambda texts: [
        [1.0 / (dimensions**0.5)] * dimensions for _ in texts
    ]
    return client


def _make_doc(
    *,
    doc_id: int,
    content: str = "Document content for the integration test.",
    modified: str = "2024-06-01T12:00:00+00:00",
    title: str | None = None,
    correspondent: int | None = None,
    tags: list[int] | None = None,
) -> dict:
    """Build a minimal Paperless document dict."""
    return {
        "id": doc_id,
        "title": title if title is not None else f"Document {doc_id}",
        "content": content,
        "tags": tags if tags is not None else [],
        "correspondent": correspondent,
        "document_type": None,
        "created": "2024-01-15",
        "modified": modified,
    }


def _make_paperless(
    *,
    documents: list[dict] | None = None,
    all_ids: list[int] | None = None,
    correspondents: list[dict] | None = None,
) -> MagicMock:
    """A mock PaperlessClient.

    iter_all_documents returns *documents* for an incremental call and bare-id
    docs for *all_ids* for a deletion-sweep call.  The two are disambiguated on
    keyword *presence*, not value: the incremental sync always passes the
    ``modified_after`` keyword (even ``None`` on a first run), while the
    deletion sweep passes no keyword at all.  Disambiguating on a ``None``
    value would misroute a first-run incremental sync to the sweep branch.
    """
    paperless = MagicMock()
    docs = documents if documents is not None else []
    ids = all_ids if all_ids is not None else []

    def _iter_all_documents(**kwargs: object) -> list[dict]:
        if "modified_after" in kwargs:
            return docs
        return [{"id": doc_id} for doc_id in ids]

    paperless.iter_all_documents.side_effect = _iter_all_documents
    paperless.list_correspondents.return_value = correspondents or []
    paperless.list_document_types.return_value = []
    paperless.list_tags.return_value = []
    paperless.document_exists.return_value = False
    return paperless


# ---------------------------------------------------------------------------
# Incremental sync — end to end against a real store
# ---------------------------------------------------------------------------


class TestIncrementalSyncEndToEnd:
    """The real reconciler indexes documents into a real store."""

    def test_new_documents_land_in_the_store_and_watermark_advances(
        self, tmp_path: Any
    ) -> None:
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            latest = "2024-06-10T09:00:00+00:00"
            docs = [
                _make_doc(doc_id=1, modified="2024-06-01T00:00:00+00:00"),
                _make_doc(doc_id=2, modified=latest),
            ]
            paperless = _make_paperless(documents=docs)
            reconciler = Reconciler(
                settings, paperless, store_writer, _make_embedding_client()
            )

            report = reconciler.incremental_sync()

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
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            content = "Boundary document — stable content."
            boundary = _make_doc(
                doc_id=5,
                content=content,
                modified="2024-06-05T12:00:00+00:00",
                title="Original Title",
            )

            # Cycle 1: index the document fresh.
            paperless_one = _make_paperless(documents=[boundary])
            reconciler_one = Reconciler(
                settings, paperless_one, store_writer, _make_embedding_client()
            )
            report_one = reconciler_one.incremental_sync()
            assert report_one.indexed == 1

            # Cycle 2: the watermark overlap re-fetches the same document, but
            # only its title has changed — the OCR content is byte-identical.
            boundary_again = _make_doc(
                doc_id=5,
                content=content,
                modified="2024-06-05T12:00:00+00:00",
                title="Title Updated By The Classifier",
            )
            embedding_two = _make_embedding_client()
            paperless_two = _make_paperless(documents=[boundary_again])
            reconciler_two = Reconciler(
                settings, paperless_two, store_writer, embedding_two
            )
            report_two = reconciler_two.incremental_sync()

            # The hash gate fired: a metadata-only update, no embedding call.
            assert report_two.metadata_only == 1
            assert report_two.indexed == 0
            embedding_two.embed.assert_not_called()
        finally:
            store_writer.close()

    def test_changed_document_is_reindexed(self, tmp_path: Any) -> None:
        """A document whose OCR content changes is re-chunked and re-embedded."""
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            original = _make_doc(doc_id=8, content="The original OCR content.")
            paperless_one = _make_paperless(documents=[original])
            Reconciler(
                settings, paperless_one, store_writer, _make_embedding_client()
            ).incremental_sync()

            original_state = store_writer.get_index_state()[8]

            # The document's content genuinely changes.
            changed = _make_doc(
                doc_id=8,
                content="Completely rewritten OCR content body.",
                modified="2024-07-01T00:00:00+00:00",
            )
            embedding_two = _make_embedding_client()
            paperless_two = _make_paperless(documents=[changed])
            report = Reconciler(
                settings, paperless_two, store_writer, embedding_two
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
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            # Seed the store via a clean first cycle so a real watermark exists.
            seed = _make_doc(doc_id=1, modified="2024-06-01T00:00:00+00:00")
            Reconciler(
                settings,
                _make_paperless(documents=[seed]),
                store_writer,
                _make_embedding_client(),
            ).incremental_sync()
            watermark_before = store_writer.read_meta("modified_watermark")
            assert watermark_before is not None

            # The next cycle's incremental enumeration fails mid-pagination.
            paperless_broken = MagicMock()

            def _iter_all_documents(**kwargs: Any):
                yield _make_doc(doc_id=2, modified="2024-07-01T00:00:00+00:00")
                raise ConnectionError("Paperless vanished mid-incremental-page")

            paperless_broken.iter_all_documents.side_effect = _iter_all_documents
            paperless_broken.list_correspondents.return_value = []
            paperless_broken.list_document_types.return_value = []
            paperless_broken.list_tags.return_value = []

            with pytest.raises(ConnectionError):
                Reconciler(
                    settings,
                    paperless_broken,
                    store_writer,
                    _make_embedding_client(),
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
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            doc = _make_doc(doc_id=1, correspondent=99)

            # Cycle 1: Paperless reports the correspondent under its old name.
            paperless_one = _make_paperless(
                documents=[doc],
                correspondents=[{"id": 99, "name": "Old Energy Co"}],
            )
            Reconciler(
                settings, paperless_one, store_writer, _make_embedding_client()
            ).incremental_sync()

            assert _correspondent_name(store_writer, 99) == "Old Energy Co"

            # Cycle 2: the correspondent has been renamed in Paperless.
            paperless_two = _make_paperless(
                documents=[doc],
                correspondents=[{"id": 99, "name": "New Energy Co Ltd"}],
            )
            Reconciler(
                settings, paperless_two, store_writer, _make_embedding_client()
            ).incremental_sync()

            # The taxonomy row now carries the new name — no document rewrite.
            assert _correspondent_name(store_writer, 99) == "New Energy Co Ltd"
        finally:
            store_writer.close()


def _correspondent_name(store_writer: StoreWriter, correspondent_id: int) -> str:
    """Read a correspondent name straight from the store's taxonomy table.

    A small test-only probe; the store does not (yet) expose a typed taxonomy
    read, and this integration test must verify the row landed.
    """
    row = store_writer._conn.execute(
        "SELECT name FROM taxonomy WHERE kind = ? AND id = ?",
        ("correspondent", correspondent_id),
    ).fetchone()
    assert row is not None
    return str(row[0])


# ---------------------------------------------------------------------------
# Deletion sweep — end to end against a real store
# ---------------------------------------------------------------------------


class TestDeletionSweepEndToEnd:
    """The real sweep prunes a real store — safely."""

    def test_complete_enumeration_prunes_only_absent_documents(
        self, tmp_path: Any
    ) -> None:
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            # Index four documents into the store.
            docs = [_make_doc(doc_id=i) for i in (1, 2, 3, 4)]
            paperless_index = _make_paperless(documents=docs)
            Reconciler(
                settings, paperless_index, store_writer, _make_embedding_client()
            ).incremental_sync()
            assert store_writer.get_all_document_ids() == {1, 2, 3, 4}

            # Paperless now only has 1 and 2 — documents 3 and 4 were deleted.
            paperless_sweep = _make_paperless(all_ids=[1, 2])
            report = Reconciler(
                settings, paperless_sweep, store_writer, _make_embedding_client()
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

        Every Paperless document was genuinely deleted.  ``iter_all_documents()``
        completes normally returning ``[]`` — it does not raise — so the
        enumeration is authoritative, and every store document is 404-confirmed
        absent and pruned.  The 404-confirm is what separates this from an
        enumeration that *failed* and returned nothing (which aborts)."""
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            docs = [_make_doc(doc_id=i) for i in (1, 2, 3)]
            Reconciler(
                settings,
                _make_paperless(documents=docs),
                store_writer,
                _make_embedding_client(),
            ).incremental_sync()
            assert store_writer.get_all_document_ids() == {1, 2, 3}

            # Paperless now has nothing — a successful, empty enumeration.
            paperless_empty = _make_paperless(all_ids=[])
            report = Reconciler(
                settings, paperless_empty, store_writer, _make_embedding_client()
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
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            docs = [_make_doc(doc_id=i) for i in (1, 2, 3)]
            Reconciler(
                settings,
                _make_paperless(documents=docs),
                store_writer,
                _make_embedding_client(),
            ).incremental_sync()

            paperless_empty = _make_paperless(all_ids=[])
            # The enumeration listed nothing, but id 2 actually still exists.
            paperless_empty.document_exists.side_effect = (
                lambda doc_id: doc_id == 2
            )
            report = Reconciler(
                settings, paperless_empty, store_writer, _make_embedding_client()
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
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            docs = [_make_doc(doc_id=i) for i in (1, 2, 3, 4, 5)]
            paperless_index = _make_paperless(documents=docs)
            Reconciler(
                settings, paperless_index, store_writer, _make_embedding_client()
            ).incremental_sync()

            before = store_writer.get_all_document_ids()
            assert before == {1, 2, 3, 4, 5}

            # The sweep's enumeration fails after two pages — a network drop.
            paperless_broken = MagicMock()

            def _iter_all_documents(*, modified_after: str | None = None):
                yield {"id": 1}
                yield {"id": 2}
                raise ConnectionError("Paperless vanished mid-pagination")

            paperless_broken.iter_all_documents.side_effect = _iter_all_documents

            report = Reconciler(
                settings, paperless_broken, store_writer, _make_embedding_client()
            ).deletion_sweep()

            assert report.aborted is True
            assert report.pruned == 0
            # The store is completely untouched — no false prune.
            assert store_writer.get_all_document_ids() == before
        finally:
            store_writer.close()

    def test_candidate_confirmed_present_is_not_pruned(self, tmp_path: Any) -> None:
        """A document missing from the page list but confirmed present is kept."""
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            docs = [_make_doc(doc_id=i) for i in (1, 2, 3)]
            Reconciler(
                settings,
                _make_paperless(documents=docs),
                store_writer,
                _make_embedding_client(),
            ).incremental_sync()

            # Enumeration lists only id 1, but the per-id confirmation says
            # id 2 still exists (a race) and id 3 is genuinely gone.
            paperless_sweep = _make_paperless(all_ids=[1])
            paperless_sweep.document_exists.side_effect = (
                lambda doc_id: doc_id == 2
            )
            report = Reconciler(
                settings, paperless_sweep, store_writer, _make_embedding_client()
            ).deletion_sweep()

            assert report.pruned == 1
            # id 2 was confirmed present → kept; id 3 → pruned.
            assert store_writer.get_all_document_ids() == {1, 2}
        finally:
            store_writer.close()


# ---------------------------------------------------------------------------
# Per-document failure isolation — end to end
# ---------------------------------------------------------------------------


class TestFailureIsolationEndToEnd:
    """A single failing document does not stop the rest of the cycle."""

    def test_one_failing_document_isolated_others_still_committed(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _make_settings(tmp_path)
        store_writer = StoreWriter(settings)
        try:
            docs = [_make_doc(doc_id=i) for i in (1, 2, 3)]
            paperless = _make_paperless(documents=docs)

            # Make the embedding client explode for document 2 only.  The
            # reconciler must catch it, count it, and carry on with 1 and 3.
            embedding_client = MagicMock()
            real_vectors = [[0.5, 0.5, 0.5, 0.5]]

            def _embed(texts: list[str]) -> list[list[float]]:
                # The failing document is identified by its unique content;
                # all three docs here share content, so fail on the 2nd call.
                _embed.calls += 1  # type: ignore[attr-defined]
                if _embed.calls == 2:  # type: ignore[attr-defined]
                    raise RuntimeError("embedding API failed for one document")
                return real_vectors * len(texts)

            _embed.calls = 0  # type: ignore[attr-defined]
            embedding_client.embed.side_effect = _embed

            report = Reconciler(
                settings, paperless, store_writer, embedding_client
            ).incremental_sync()

            # Exactly one document failed; the other two committed.
            assert report.failed == 1
            assert report.indexed == 2
            assert len(store_writer.get_all_document_ids()) == 2
        finally:
            store_writer.close()
