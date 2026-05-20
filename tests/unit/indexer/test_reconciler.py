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

    def test_failing_document_does_not_advance_the_watermark(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pass with any failure is not 'fully successful' → watermark frozen."""
        watermark = "2024-05-01T00:00:00+00:00"
        docs = [
            _make_doc(doc_id=1, modified="2024-06-09T00:00:00+00:00"),
            _make_doc(doc_id=2, modified="2024-06-10T00:00:00+00:00"),
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
        # The watermark must NOT advance — a failed document would otherwise be
        # silently skipped forever once the watermark moves past it.
        assert store_writer._meta["modified_watermark"] == watermark

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
        report = SyncReport(indexed=1, metadata_only=0, skipped=0, failed=0)
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
