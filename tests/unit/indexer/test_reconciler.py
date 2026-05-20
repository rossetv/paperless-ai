"""Tests for indexer.reconciler.Reconciler.

The reconciler is the indexer's correctness-critical engine.  These tests pin
its two public behaviours:

incremental_sync (SPEC §5.2):
- Reads the modified_watermark, pages Paperless from it, fans documents across
  a worker pool, and advances the watermark on a fully-successful pass.
- The watermark overlap re-includes a boundary document next cycle; the
  content-hash gate makes that re-inclusion a cheap METADATA_ONLY no-op.
- A changed document is re-indexed.
- Taxonomy is refreshed every cycle (a renamed correspondent propagates).
- A single failing document is isolated and counted; the cycle continues.

deletion_sweep (SPEC §5.4 — non-negotiable safety rules):
- A complete enumeration prunes ONLY the truly-absent ids.
- An enumeration that raises mid-pagination prunes NOTHING (the data-loss
  prevention case).
- A candidate that document_exists still confirms present is NOT pruned.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from indexer.reconciler import (
    MAX_DOCUMENT_FAILURES,
    OVERLAP_MARGIN,
    Reconciler,
    SweepReport,
    SyncReport,
)
from indexer.worker import IndexOutcome
from store.models import IndexState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(*, document_workers: int = 2) -> MagicMock:
    """Return a settings mock with the fields the reconciler reads."""
    settings = MagicMock()
    settings.DOCUMENT_WORKERS = document_workers
    return settings


def _make_paperless(
    *,
    documents: list[dict] | None = None,
    all_ids: list[int] | None = None,
) -> MagicMock:
    """Return a mock PaperlessClient.

    The incremental sync calls ``iter_all_documents(modified_after=...)`` — the
    keyword is always passed, even when its value is None on the first run.
    The deletion sweep calls ``iter_all_documents()`` with no keyword at all.
    The side effect disambiguates on keyword *presence*: an incremental call
    yields *documents*, a sweep call yields *all_ids* as bare-id docs.
    """
    paperless = MagicMock()
    docs = documents if documents is not None else []
    ids = all_ids if all_ids is not None else []

    def _iter_all_documents(**kwargs: object) -> list[dict]:
        if "modified_after" in kwargs:
            return docs
        return [{"id": doc_id} for doc_id in ids]

    paperless.iter_all_documents.side_effect = _iter_all_documents
    paperless.list_correspondents.return_value = []
    paperless.list_document_types.return_value = []
    paperless.list_tags.return_value = []
    paperless.document_exists.return_value = False
    return paperless


def _make_store_writer(
    *,
    watermark: str | None = None,
    index_state: dict[int, IndexState] | None = None,
    store_ids: set[int] | None = None,
) -> MagicMock:
    """Return a mock StoreWriter with read methods stubbed."""
    store_writer = MagicMock()
    meta: dict[str, str] = {}
    if watermark is not None:
        meta["modified_watermark"] = watermark
    store_writer.read_meta.side_effect = lambda key: meta.get(key)
    store_writer.write_meta.side_effect = lambda key, value: meta.__setitem__(
        key, value
    )
    store_writer._meta = meta  # exposed for assertions
    store_writer.get_index_state.return_value = index_state or {}
    store_writer.get_all_document_ids.return_value = store_ids or set()
    return store_writer


def _make_embedding_client() -> MagicMock:
    """Return a mock EmbeddingClient (the reconciler only forwards it)."""
    return MagicMock()


def _make_doc(
    *,
    doc_id: int,
    modified: str = "2024-06-01T12:00:00+00:00",
    content: str = "Document content.",
) -> dict:
    """Build a minimal Paperless document dict."""
    return {
        "id": doc_id,
        "title": f"Document {doc_id}",
        "content": content,
        "tags": [],
        "correspondent": None,
        "document_type": None,
        "created": "2024-01-15",
        "modified": modified,
    }


# ---------------------------------------------------------------------------
# incremental_sync — indexing new documents and advancing the watermark
# ---------------------------------------------------------------------------


class TestIncrementalSyncIndexesNewDocuments:
    """A first cycle indexes every returned document and advances the watermark."""

    def test_new_documents_are_indexed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        docs = [_make_doc(doc_id=1), _make_doc(doc_id=2)]
        paperless = _make_paperless(documents=docs)
        store_writer = _make_store_writer()

        index_calls: list[int] = []

        def _index_document(_self: object, doc: dict, existing: IndexState | None) -> IndexOutcome:
            index_calls.append(doc["id"])
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            _index_document,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.incremental_sync()

        assert sorted(index_calls) == [1, 2]
        assert report.indexed == 2
        assert report.failed == 0

    def test_watermark_advances_to_max_modified_minus_overlap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fully-successful pass advances the watermark to max(modified) - OVERLAP."""
        latest = "2024-06-10T08:30:00+00:00"
        docs = [
            _make_doc(doc_id=1, modified="2024-06-01T00:00:00+00:00"),
            _make_doc(doc_id=2, modified=latest),
        ]
        paperless = _make_paperless(documents=docs)
        store_writer = _make_store_writer()

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        reconciler.incremental_sync()

        expected = (
            datetime.fromisoformat(latest) - OVERLAP_MARGIN
        ).isoformat()
        assert store_writer._meta["modified_watermark"] == expected

    def test_first_run_reads_no_watermark_and_queries_from_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no stored watermark, iter_all_documents is called with modified_after=None."""
        paperless = _make_paperless(documents=[_make_doc(doc_id=1)])
        store_writer = _make_store_writer(watermark=None)

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        reconciler.incremental_sync()

        # The first (and only) incremental call uses modified_after=None.
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
        paperless = _make_paperless(documents=[])
        store_writer = _make_store_writer(watermark=watermark)

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        reconciler.incremental_sync()

        paperless.iter_all_documents.assert_called_once_with(
            modified_after=watermark
        )

    def test_empty_cycle_does_not_change_the_watermark(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No documents returned → nothing to advance to → watermark untouched."""
        watermark = "2024-05-01T00:00:00+00:00"
        paperless = _make_paperless(documents=[])
        store_writer = _make_store_writer(watermark=watermark)

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.incremental_sync()

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
        content_hash matches.  The reconciler must pass that existing state, so
        the gate fires and the re-inclusion is free (no re-embed).
        """
        import hashlib

        content = "Stable boundary content."
        boundary_modified = "2024-06-01T12:00:00+00:00"
        boundary_doc = _make_doc(
            doc_id=7, modified=boundary_modified, content=content
        )
        paperless = _make_paperless(documents=[boundary_doc])

        existing_hash = hashlib.sha256(content.encode()).hexdigest()
        index_state = {
            7: IndexState(modified=boundary_modified, content_hash=existing_hash)
        }
        store_writer = _make_store_writer(
            watermark=boundary_modified, index_state=index_state
        )

        captured_existing: list[IndexState | None] = []

        def _index_document(_self: object, doc: dict, existing: IndexState | None) -> IndexOutcome:
            captured_existing.append(existing)
            # Mirror the real worker's hash-gate decision.
            import hashlib as _hashlib

            doc_hash = _hashlib.sha256(doc["content"].encode()).hexdigest()
            if existing is not None and existing.content_hash == doc_hash:
                return IndexOutcome.METADATA_ONLY
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            _index_document,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.incremental_sync()

        # The reconciler passed the document's existing IndexState.
        assert captured_existing == [index_state[7]]
        # The hash gate fired: a cheap metadata-only update, not a re-index.
        assert report.metadata_only == 1
        assert report.indexed == 0

    def test_changed_document_is_reindexed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A document whose content hash differs from the store is re-indexed."""
        changed_doc = _make_doc(doc_id=3, content="Brand new content body.")
        paperless = _make_paperless(documents=[changed_doc])

        # The store holds a stale hash for document 3.
        index_state = {
            3: IndexState(
                modified="2024-05-01T00:00:00+00:00",
                content_hash="stale-hash-does-not-match",
            )
        }
        store_writer = _make_store_writer(index_state=index_state)

        def _index_document(_self: object, doc: dict, existing: IndexState | None) -> IndexOutcome:
            import hashlib

            doc_hash = hashlib.sha256(doc["content"].encode()).hexdigest()
            if existing is not None and existing.content_hash == doc_hash:
                return IndexOutcome.METADATA_ONLY
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            _index_document,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.incremental_sync()

        assert report.indexed == 1
        assert report.metadata_only == 0


# ---------------------------------------------------------------------------
# incremental_sync — taxonomy refresh every cycle
# ---------------------------------------------------------------------------


class TestIncrementalSyncRefreshesTaxonomy:
    """Every cycle rebuilds the taxonomy so a Paperless rename propagates."""

    def test_taxonomy_is_refreshed_with_correspondents_types_and_tags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paperless = _make_paperless(documents=[])
        paperless.list_correspondents.return_value = [
            {"id": 1, "name": "npower"}
        ]
        paperless.list_document_types.return_value = [
            {"id": 2, "name": "Invoice"}
        ]
        paperless.list_tags.return_value = [{"id": 3, "name": "urgent"}]
        store_writer = _make_store_writer()

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        reconciler.incremental_sync()

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
        paperless = _make_paperless(documents=[])
        # Paperless now reports the correspondent under a new name.
        paperless.list_correspondents.return_value = [
            {"id": 42, "name": "Npower Renamed Ltd"}
        ]
        store_writer = _make_store_writer()

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        reconciler.incremental_sync()

        entries = list(store_writer.refresh_taxonomy.call_args[0][0])
        correspondent = next(e for e in entries if e.kind == "correspondent")
        assert correspondent.id == 42
        assert correspondent.name == "Npower Renamed Ltd"

    def test_taxonomy_refreshed_once_not_per_document(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The taxonomy maps are built once per cycle, not per document (§14.5)."""
        docs = [_make_doc(doc_id=i) for i in range(1, 6)]
        paperless = _make_paperless(documents=docs)
        store_writer = _make_store_writer()

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        reconciler.incremental_sync()

        assert store_writer.refresh_taxonomy.call_count == 1
        assert paperless.list_correspondents.call_count == 1
        assert paperless.list_document_types.call_count == 1
        assert paperless.list_tags.call_count == 1


# ---------------------------------------------------------------------------
# incremental_sync — per-document failure isolation (SPEC §5.7)
# ---------------------------------------------------------------------------


class TestIncrementalSyncIsolatesFailures:
    """A single failing document never aborts the cycle (SPEC §5.7)."""

    def test_one_failing_document_does_not_abort_the_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs = [_make_doc(doc_id=1), _make_doc(doc_id=2), _make_doc(doc_id=3)]
        paperless = _make_paperless(documents=docs)
        store_writer = _make_store_writer()

        def _index_document(_self: object, doc: dict, existing: IndexState | None) -> IndexOutcome:
            if doc["id"] == 2:
                raise RuntimeError("embedding API exploded for document 2")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            _index_document,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.incremental_sync()

        # Documents 1 and 3 still indexed; 2 counted as failed.
        assert report.indexed == 2
        assert report.failed == 1

    def test_failing_document_advances_watermark_and_is_tracked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failure no longer freezes the watermark — it advances unconditionally.

        Forward progress is decoupled from failure retry: a page that held a
        document advances the watermark to ``max(modified) - OVERLAP`` even
        when one document failed, and the failed document is recorded in the
        persisted ``failed_documents`` map for an out-of-band retry next cycle.
        Freezing the watermark on failure was the old bug — a permanently
        failing document would have stalled the watermark forever.
        """
        import json

        watermark = "2024-05-01T00:00:00+00:00"
        latest = "2024-06-10T00:00:00+00:00"
        docs = [
            _make_doc(doc_id=1, modified="2024-06-09T00:00:00+00:00"),
            _make_doc(doc_id=2, modified=latest),
        ]
        paperless = _make_paperless(documents=docs)
        store_writer = _make_store_writer(watermark=watermark)

        def _index_document(_self: object, doc: dict, existing: IndexState | None) -> IndexOutcome:
            if doc["id"] == 2:
                raise RuntimeError("document 2 failed")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            _index_document,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.incremental_sync()

        assert report.failed == 1
        assert report.given_up == 0
        # The watermark advanced despite the failure — failures are tracked
        # separately, not by stalling forward progress.
        expected = (
            datetime.fromisoformat(latest) - OVERLAP_MARGIN
        ).isoformat()
        assert store_writer._meta["modified_watermark"] == expected
        # The failed document is recorded for retry with one consecutive failure.
        failed_map = json.loads(store_writer._meta["failed_documents"])
        assert failed_map == {"2": 1}

    def test_skipped_documents_are_counted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs = [_make_doc(doc_id=1), _make_doc(doc_id=2)]
        paperless = _make_paperless(documents=docs)
        store_writer = _make_store_writer()

        def _index_document(_self: object, doc: dict, existing: IndexState | None) -> IndexOutcome:
            if doc["id"] == 1:
                return IndexOutcome.SKIPPED
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            _index_document,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.incremental_sync()

        assert report.skipped == 1
        assert report.indexed == 1

    def test_partial_incremental_enumeration_leaves_watermark_unmoved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mid-pagination failure during INCREMENTAL sync must not move the
        watermark.

        The incremental page is materialised with ``list(iter_all_documents(...))``
        before any document is indexed.  If that generator yields one document
        then raises mid-pagination, the failure propagates out of
        ``incremental_sync`` (the daemon's cycle boundary — C1 — catches it),
        and crucially the watermark must be byte-for-byte unchanged: advancing
        it on a partial page would silently skip every not-yet-seen document.
        """
        watermark = "2024-05-01T00:00:00+00:00"
        store_writer = _make_store_writer(watermark=watermark)

        paperless = MagicMock()

        def _iter_all_documents(**kwargs: object):
            # Incremental call (modified_after present): yield one, then fail.
            yield _make_doc(doc_id=1, modified="2024-06-09T00:00:00+00:00")
            raise ConnectionError("Paperless dropped mid-incremental-pagination")

        paperless.iter_all_documents.side_effect = _iter_all_documents
        paperless.list_correspondents.return_value = []
        paperless.list_document_types.return_value = []
        paperless.list_tags.return_value = []

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )

        # The paging failure propagates — the daemon's cycle boundary handles it.
        with pytest.raises(ConnectionError):
            reconciler.incremental_sync()

        # The watermark is exactly where it started — a partial page is never
        # treated as authoritative.
        assert store_writer._meta["modified_watermark"] == watermark


# ---------------------------------------------------------------------------
# incremental_sync — bounded failed-document retry and dead-lettering (I1)
# ---------------------------------------------------------------------------


class TestIncrementalSyncFailedDocumentRetry:
    """A permanently-failing document is retried, bounded, and dead-lettered.

    The old design froze the watermark on any failure — a document that failed
    every cycle stalled the watermark forever and re-embedded the whole growing
    changed tail.  The fix decouples forward progress from failure retry: the
    watermark advances unconditionally, while failed documents are tracked in a
    persisted ``failed_documents`` map, retried out-of-band each cycle, and
    dead-lettered after ``MAX_DOCUMENT_FAILURES`` consecutive failures.
    """

    def test_permanently_failing_document_is_retried_then_dead_lettered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A document that fails every cycle is retried via the failed-id set,
        dead-lettered after MAX_DOCUMENT_FAILURES with a CRITICAL log, and the
        watermark advances the whole time — never frozen."""
        import json

        import structlog.testing

        poison_id = 99

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            if doc["id"] == poison_id:
                raise RuntimeError(f"document {poison_id} is poison")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            _index_document,
        )

        # One store survives across every cycle so failed_documents and the
        # watermark persist — exactly the daemon's reuse pattern.
        store_writer = _make_store_writer()

        watermarks_seen: list[str | None] = []

        for cycle in range(MAX_DOCUMENT_FAILURES):
            # The healthy document's modified advances each cycle so the
            # watermark has somewhere new to move to.
            healthy_modified = f"2024-06-{10 + cycle:02d}T00:00:00+00:00"
            healthy = _make_doc(doc_id=1, modified=healthy_modified)

            if cycle == 0:
                # Cycle 1: the poison document is in the watermark page.
                page = [healthy, _make_doc(doc_id=poison_id)]
                paperless = _make_paperless(documents=page)
            else:
                # Later cycles: the poison document is PAST the advanced
                # watermark, so it is no longer in the page — it must be
                # re-fetched out-of-band via the failed_documents retry path.
                paperless = _make_paperless(documents=[healthy])
                paperless.document_exists.return_value = True
                paperless.get_document.return_value = _make_doc(
                    doc_id=poison_id
                )

            watermarks_seen.append(
                store_writer.read_meta("modified_watermark")
            )

            reconciler = Reconciler(
                _make_settings(), paperless, store_writer,
                _make_embedding_client(),
            )
            # capture_logs intercepts structlog events as dicts regardless of
            # the configured renderer — the project does not route structlog
            # through stdlib logging, so caplog would see nothing.
            with structlog.testing.capture_logs() as captured:
                report = reconciler.incremental_sync()

            if cycle == 0:
                # First failure recorded; the poison doc was in the page so no
                # out-of-band re-fetch happened yet.
                paperless.get_document.assert_not_called()
            else:
                # The poison doc was re-fetched out-of-band by id.
                paperless.get_document.assert_called_once_with(poison_id)

            if cycle < MAX_DOCUMENT_FAILURES - 1:
                # Still being retried — failed, not yet given up.
                assert report.failed == 1
                assert report.given_up == 0
                failed_map = json.loads(
                    store_writer._meta["failed_documents"]
                )
                assert failed_map == {str(poison_id): cycle + 1}
                # No give-up log yet.
                assert not [
                    e
                    for e in captured
                    if e["event"] == "reconcile.document_given_up"
                ]
            else:
                # The final cycle reaches MAX_DOCUMENT_FAILURES → dead-lettered.
                assert report.failed == 1
                assert report.given_up == 1
                # Dropped from the retry map — no longer retried.
                failed_map = json.loads(
                    store_writer._meta["failed_documents"]
                )
                assert str(poison_id) not in failed_map
                # A CRITICAL log names the document and the give-up reason.
                give_up_logs = [
                    e
                    for e in captured
                    if e["event"] == "reconcile.document_given_up"
                ]
                assert len(give_up_logs) == 1
                assert give_up_logs[0]["log_level"] == "critical"
                assert give_up_logs[0]["document_id"] == poison_id
                assert (
                    give_up_logs[0]["consecutive_failures"]
                    == MAX_DOCUMENT_FAILURES
                )

        # The watermark advanced on EVERY cycle — it was never frozen by the
        # permanently-failing document.  Each cycle saw a strictly newer
        # watermark than the cycle before (None on the first read).
        assert watermarks_seen[0] is None
        non_null = watermarks_seen[1:]
        assert non_null == sorted(non_null)
        assert len(set(non_null)) == len(non_null)  # strictly increasing

    def test_document_that_fails_once_then_succeeds_is_cleared_from_the_map(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transient failure is recorded, then cleared the cycle it succeeds."""
        import json

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
            "indexer.reconciler.DocumentIndexer.index_document",
            _index_document,
        )

        store_writer = _make_store_writer()

        # Cycle 1: the flaky document is in the page and fails.
        paperless_one = _make_paperless(
            documents=[_make_doc(doc_id=flaky_id, modified="2024-06-10T00:00:00+00:00")]
        )
        report_one = Reconciler(
            _make_settings(), paperless_one, store_writer, _make_embedding_client()
        ).incremental_sync()

        assert report_one.failed == 1
        assert json.loads(store_writer._meta["failed_documents"]) == {
            str(flaky_id): 1
        }

        # Cycle 2: the watermark has advanced past the flaky document, so it is
        # re-fetched out-of-band — and this time it succeeds.
        paperless_two = _make_paperless(documents=[])
        paperless_two.document_exists.return_value = True
        paperless_two.get_document.return_value = _make_doc(
            doc_id=flaky_id, modified="2024-06-10T00:00:00+00:00"
        )
        report_two = Reconciler(
            _make_settings(), paperless_two, store_writer, _make_embedding_client()
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
        import json

        gone_id = 13

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            lambda _self, doc, existing: (_ for _ in ()).throw(
                RuntimeError(f"document {doc['id']} failed")
            )
            if doc["id"] == gone_id
            else IndexOutcome.INDEXED,
        )

        store_writer = _make_store_writer()

        # Cycle 1: the document is in the page and fails.
        paperless_one = _make_paperless(documents=[_make_doc(doc_id=gone_id)])
        Reconciler(
            _make_settings(), paperless_one, store_writer, _make_embedding_client()
        ).incremental_sync()
        assert json.loads(store_writer._meta["failed_documents"]) == {
            str(gone_id): 1
        }

        # Cycle 2: the document has been deleted from Paperless — document_exists
        # returns False, so the failed-document re-fetch must drop it.
        paperless_two = _make_paperless(documents=[])
        paperless_two.document_exists.return_value = False
        report = Reconciler(
            _make_settings(), paperless_two, store_writer, _make_embedding_client()
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
        import json

        monkeypatch.setattr(
            "indexer.reconciler.DocumentIndexer.index_document",
            lambda _self, doc, existing: IndexOutcome.INDEXED,
        )

        store_writer = _make_store_writer()
        # Seed the meta with garbage that is not a JSON object of int counts.
        store_writer._meta["failed_documents"] = "{not valid json"

        paperless = _make_paperless(documents=[_make_doc(doc_id=1)])
        report = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        ).incremental_sync()

        # The cycle completed and rewrote a clean (empty) map.
        assert report.indexed == 1
        assert json.loads(store_writer._meta["failed_documents"]) == {}


# ---------------------------------------------------------------------------
# deletion_sweep — the safety rules (SPEC §5.4)
# ---------------------------------------------------------------------------


class TestDeletionSweepCompleteEnumeration:
    """A complete enumeration prunes ONLY the truly-absent ids."""

    def test_prunes_only_ids_absent_from_paperless(self) -> None:
        # Paperless has 1 and 2; the store also has a stale 3 and 4.
        paperless = _make_paperless(all_ids=[1, 2])
        store_writer = _make_store_writer(store_ids={1, 2, 3, 4})

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.deletion_sweep()

        store_writer.delete_documents.assert_called_once()
        pruned = set(store_writer.delete_documents.call_args[0][0])
        assert pruned == {3, 4}
        assert report.pruned == 2

    def test_nothing_to_prune_when_store_matches_paperless(self) -> None:
        paperless = _make_paperless(all_ids=[1, 2, 3])
        store_writer = _make_store_writer(store_ids={1, 2, 3})

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.deletion_sweep()

        assert report.pruned == 0
        # delete_documents may be called with an empty set or skipped; either
        # way nothing is pruned.
        if store_writer.delete_documents.called:
            assert set(store_writer.delete_documents.call_args[0][0]) == set()

    def test_completed_sweep_records_last_full_sweep_at(self) -> None:
        paperless = _make_paperless(all_ids=[1])
        store_writer = _make_store_writer(store_ids={1})

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        reconciler.deletion_sweep()

        assert "last_full_sweep_at" in store_writer._meta

    def test_empty_complete_enumeration_prunes_every_confirmed_absent_document(
        self,
    ) -> None:
        """The dangerous boundary: a SUCCESSFUL enumeration yielding zero ids.

        Paperless genuinely has no documents (every one was deleted).
        ``iter_all_documents()`` completes normally yielding ``[]`` — it does
        NOT raise — so the enumeration is authoritative, and every store
        document, once 404-confirmed absent, is pruned.  This is distinct from
        an enumeration that *fails* and returns nothing: that one aborts (see
        TestDeletionSweepPartialEnumerationPrunesNothing).  The 404-confirm is
        the guard that tells the two apart.
        """
        paperless = _make_paperless(all_ids=[])  # successful, empty result
        # document_exists returns False by default → all confirmed absent.
        store_writer = _make_store_writer(store_ids={1, 2, 3})

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.deletion_sweep()

        assert report.aborted is False
        assert report.candidates == 3
        assert report.pruned == 3
        store_writer.delete_documents.assert_called_once()
        assert set(store_writer.delete_documents.call_args[0][0]) == {1, 2, 3}
        # A genuine complete sweep — completion is recorded.
        assert "last_full_sweep_at" in store_writer._meta

    def test_empty_enumeration_keeps_documents_the_404_confirm_says_exist(
        self,
    ) -> None:
        """Even on an empty enumeration, a candidate the 404-confirm reports
        PRESENT is kept — the per-id confirmation is the real deletion guard."""
        paperless = _make_paperless(all_ids=[])  # successful, empty result
        # The enumeration listed nothing, but id 2 actually still exists — a
        # document created in the window between enumeration and confirmation.
        paperless.document_exists.side_effect = lambda doc_id: doc_id == 2
        store_writer = _make_store_writer(store_ids={1, 2, 3})

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.deletion_sweep()

        assert report.aborted is False
        # id 2 was confirmed present → survives; 1 and 3 → pruned.
        assert report.pruned == 2
        assert set(store_writer.delete_documents.call_args[0][0]) == {1, 3}


class TestDeletionSweepPartialEnumerationPrunesNothing:
    """THE critical case: a mid-pagination failure must prune NOTHING."""

    def test_page_failure_mid_enumeration_prunes_nothing(self) -> None:
        """If iter_all_documents raises mid-pagination, the store is untouched.

        A partial enumeration would make every not-yet-seen document look
        deleted.  The sweep must abort and prune NOTHING (SPEC §5.4 rule 2) —
        this prevents catastrophic data loss when Paperless is briefly
        unreachable during pagination.
        """
        paperless = MagicMock()

        def _iter_all_documents(*, modified_after: str | None = None):
            # Yield a couple of ids, then fail mid-pagination — exactly the
            # shape of a network drop between pages.
            yield {"id": 1}
            yield {"id": 2}
            raise ConnectionError("Paperless unreachable mid-pagination")

        paperless.iter_all_documents.side_effect = _iter_all_documents

        # The store holds ids that are NOT in the partial enumeration; a naive
        # diff would prune 3, 4, 5 — that is the data-loss footgun.
        store_writer = _make_store_writer(store_ids={1, 2, 3, 4, 5})

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.deletion_sweep()

        # The store must be completely untouched.
        store_writer.delete_documents.assert_not_called()
        assert report.pruned == 0
        assert report.aborted is True
        # The sweep did not complete, so last_full_sweep_at must not advance.
        assert "last_full_sweep_at" not in store_writer._meta

    def test_first_page_failure_prunes_nothing(self) -> None:
        """An immediate enumeration failure also prunes nothing."""
        paperless = MagicMock()

        def _iter_all_documents(*, modified_after: str | None = None):
            raise ConnectionError("Paperless down before the first page")
            yield  # pragma: no cover — unreachable, makes this a generator

        paperless.iter_all_documents.side_effect = _iter_all_documents
        store_writer = _make_store_writer(store_ids={10, 11, 12})

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.deletion_sweep()

        store_writer.delete_documents.assert_not_called()
        assert report.aborted is True
        assert report.pruned == 0


class TestDeletionSweepConfirmsBeforePruning:
    """Each candidate is 404-confirmed before it is pruned (SPEC §5.4 rule 3)."""

    def test_candidate_still_present_is_not_pruned(self) -> None:
        """A candidate that document_exists confirms PRESENT is kept.

        document_exists is the second confirmation against a race: the document
        appeared absent from the page enumeration but actually still exists
        (e.g. created between the enumeration and the confirmation).
        """
        # Enumeration says Paperless has only id 1; the store has 1 and 2.
        paperless = _make_paperless(all_ids=[1])
        # But the per-id confirmation says id 2 DOES still exist.
        paperless.document_exists.side_effect = lambda doc_id: doc_id == 2
        store_writer = _make_store_writer(store_ids={1, 2})

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.deletion_sweep()

        # id 2 was confirmed present → it must not be pruned.
        assert report.pruned == 0
        if store_writer.delete_documents.called:
            assert 2 not in set(store_writer.delete_documents.call_args[0][0])

    def test_only_confirmed_absent_candidates_are_pruned(self) -> None:
        """When several candidates exist, only the 404-confirmed ones are pruned."""
        paperless = _make_paperless(all_ids=[1])
        # id 2 still exists (race); id 3 and id 4 are genuinely gone.
        paperless.document_exists.side_effect = lambda doc_id: doc_id == 2
        store_writer = _make_store_writer(store_ids={1, 2, 3, 4})

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        report = reconciler.deletion_sweep()

        pruned = set(store_writer.delete_documents.call_args[0][0])
        assert pruned == {3, 4}
        assert report.pruned == 2

    def test_document_exists_is_called_for_each_candidate(self) -> None:
        paperless = _make_paperless(all_ids=[1])
        store_writer = _make_store_writer(store_ids={1, 5, 6})

        reconciler = Reconciler(
            _make_settings(), paperless, store_writer, _make_embedding_client()
        )
        reconciler.deletion_sweep()

        confirmed = {
            call.args[0] for call in paperless.document_exists.call_args_list
        }
        assert confirmed == {5, 6}


# ---------------------------------------------------------------------------
# Report shapes
# ---------------------------------------------------------------------------


class TestReportShapes:
    """SyncReport and SweepReport are frozen dataclasses (SPEC contract)."""

    def test_sync_report_is_frozen(self) -> None:
        report = SyncReport(
            indexed=1, metadata_only=0, skipped=0, failed=0, given_up=0
        )
        with pytest.raises(Exception):
            report.indexed = 99  # type: ignore[misc]

    def test_sweep_report_is_frozen(self) -> None:
        report = SweepReport(pruned=0, aborted=False, candidates=0)
        with pytest.raises(Exception):
            report.pruned = 99  # type: ignore[misc]

    def test_overlap_margin_is_a_short_timedelta(self) -> None:
        """OVERLAP_MARGIN is a few seconds — long enough to absorb a boundary
        race, short enough that re-processing is trivial."""
        assert isinstance(OVERLAP_MARGIN, timedelta)
        assert timedelta(0) < OVERLAP_MARGIN <= timedelta(minutes=1)
