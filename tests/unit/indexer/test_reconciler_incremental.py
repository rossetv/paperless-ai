"""Tests for the reconciler's watermark-driven incremental sync."""

from __future__ import annotations

import hashlib
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from common.clock import normalise_paperless_timestamp
from indexer.reconciler import OVERLAP_MARGIN
from indexer.worker import IndexOutcome
from store.models import IndexState
from tests.helpers.factories import make_paperless_document
from tests.unit.indexer.conftest import (
    always_indexed,
    make_reconciler_paperless,
    make_reconciler_store_writer,
    run_incremental_sync,
)


def _hash_gated_index_document(
    _self: object, doc: dict, existing: IndexState | None
) -> IndexOutcome:
    """A ``DocumentIndexer.index_document`` stub that mirrors the content-hash gate."""
    doc_hash = hashlib.sha256(doc["content"].encode()).hexdigest()
    if existing is not None and existing.content_hash == doc_hash:
        return IndexOutcome.METADATA_ONLY
    return IndexOutcome.INDEXED


class TestIncrementalSyncIndexesNewDocuments:
    """A first cycle indexes every returned document and advances the watermark."""

    def test_new_documents_are_indexed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        docs = [
            make_paperless_document(doc_id=1),
            make_paperless_document(doc_id=2),
        ]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer()

        index_calls: list[int] = []

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            index_calls.append(doc["id"])
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert sorted(index_calls) == [1, 2]
        assert report.indexed == 2
        assert report.failed == 0

    def test_watermark_advances_to_max_modified_minus_overlap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        latest = "2024-06-10T08:30:00+00:00"
        docs = [
            make_paperless_document(doc_id=1, modified="2024-06-01T00:00:00+00:00"),
            make_paperless_document(doc_id=2, modified=latest),
        ]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer()

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        expected = (datetime.fromisoformat(latest) - OVERLAP_MARGIN).isoformat()
        assert store_writer._meta["modified_watermark"] == expected

    def test_first_run_reads_no_watermark_and_queries_from_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paperless = make_reconciler_paperless(
            documents=[make_paperless_document(doc_id=1)]
        )
        store_writer = make_reconciler_store_writer(watermark=None)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        incremental_calls = [
            call
            for call in paperless.iter_all_documents.call_args_list
            if call.kwargs.get("modified_after") is None
        ]
        assert len(incremental_calls) == 1

    def test_stored_watermark_is_passed_as_modified_after(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stored watermark selects the light ``{id, modified}`` projection."""
        from indexer.reconciler._light_diff import _LIGHT_DIFF_FIELDS

        watermark = "2024-05-01T00:00:00+00:00"
        paperless = make_reconciler_paperless(documents=[])
        store_writer = make_reconciler_store_writer(watermark=watermark)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        paperless.iter_all_documents.assert_called_once_with(
            modified_after=watermark, fields=_LIGHT_DIFF_FIELDS
        )

    def test_empty_cycle_does_not_change_the_watermark(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        watermark = "2024-05-01T00:00:00+00:00"
        paperless = make_reconciler_paperless(documents=[])
        store_writer = make_reconciler_store_writer(watermark=watermark)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        report = run_incremental_sync(paperless, store_writer)

        assert store_writer._meta["modified_watermark"] == watermark
        assert report.indexed == 0


class TestIncrementalSyncWatermarkOverlap:
    """The overlap re-includes a boundary document; the hash gate makes it cheap."""

    def test_boundary_document_reincluded_is_skipped_cold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A re-included document whose ``modified`` matches the store is skipped
        without fetching its body or invoking the worker."""
        content = "Stable boundary content."
        boundary_modified = "2024-06-01T12:00:00+00:00"
        boundary_doc = make_paperless_document(
            doc_id=7, modified=boundary_modified, content=content
        )
        paperless = make_reconciler_paperless(documents=[boundary_doc])

        existing_hash = hashlib.sha256(content.encode()).hexdigest()
        index_state = {
            7: IndexState(
                modified=normalise_paperless_timestamp(boundary_modified),
                content_hash=existing_hash,
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark=boundary_modified, index_state=index_state
        )

        captured_existing: list[IndexState | None] = []

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            captured_existing.append(existing)
            return _hash_gated_index_document(_self, doc, existing)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert captured_existing == []
        paperless.get_document.assert_not_called()
        assert report.indexed == 0
        assert report.metadata_only == 0

    def test_changed_document_is_reindexed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        changed_doc = make_paperless_document(
            doc_id=3, content="Brand new content body."
        )
        paperless = make_reconciler_paperless(documents=[changed_doc])

        index_state = {
            3: IndexState(
                modified="2024-05-01T00:00:00+00:00",
                content_hash="stale-hash-does-not-match",
            )
        }
        store_writer = make_reconciler_store_writer(index_state=index_state)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            _hash_gated_index_document,
        )

        report = run_incremental_sync(paperless, store_writer)

        assert report.indexed == 1
        assert report.metadata_only == 0


class TestIncrementalSyncIsolatesFailures:
    """A single failing document never aborts the cycle."""

    def test_one_failing_document_does_not_abort_the_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs = [make_paperless_document(doc_id=i) for i in (1, 2, 3)]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer()

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            if doc["id"] == 2:
                raise RuntimeError("embedding API exploded for document 2")
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert report.indexed == 2
        assert report.failed == 1

    def test_skipped_documents_are_counted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs = [make_paperless_document(doc_id=i) for i in (1, 2)]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer()

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            if doc["id"] == 1:
                return IndexOutcome.SKIPPED
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert report.skipped == 1
        assert report.indexed == 1

    def test_partial_incremental_enumeration_leaves_watermark_unmoved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The paging failure propagates to the daemon's cycle boundary."""
        watermark = "2024-05-01T00:00:00+00:00"
        store_writer = make_reconciler_store_writer(watermark=watermark)

        paperless = MagicMock()

        def _iter_all_documents(**kwargs: object):
            yield make_paperless_document(
                doc_id=1, modified="2024-06-09T00:00:00+00:00"
            )
            raise ConnectionError("Paperless dropped mid-incremental-pagination")

        paperless.iter_all_documents.side_effect = _iter_all_documents
        paperless.list_correspondents.return_value = []
        paperless.list_document_types.return_value = []
        paperless.list_tags.return_value = []

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        with pytest.raises(ConnectionError):
            run_incremental_sync(paperless, store_writer)

        assert store_writer._meta["modified_watermark"] == watermark


class TestIncrementalSyncStreamsThePageStream:
    """The watermark page is consumed in batches, not materialised whole.

    A first-run backfill has no server filter, so materialising the page would
    pull every document's OCR body into memory at once.
    """

    def test_indexing_interleaves_with_paging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The generator records the indexed count at each ``yield``; a later
        yield sees a non-zero count only if indexing interleaves with paging."""
        from indexer.reconciler._incremental import _WATERMARK_PAGE_BATCH_SIZE

        total = _WATERMARK_PAGE_BATCH_SIZE * 2 + 1
        indexed_count = 0
        counts_at_yield: list[int] = []

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            nonlocal indexed_count
            indexed_count += 1
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        def _document_stream(**kwargs: object):
            for doc_id in range(1, total + 1):
                counts_at_yield.append(indexed_count)
                yield make_paperless_document(doc_id=doc_id)

        paperless = MagicMock()
        paperless.iter_all_documents.side_effect = _document_stream
        paperless.list_correspondents.return_value = []
        paperless.list_document_types.return_value = []
        paperless.list_tags.return_value = []
        paperless.document_exists.return_value = False
        store_writer = make_reconciler_store_writer()

        report = run_incremental_sync(paperless, store_writer)

        assert report.indexed == total
        assert counts_at_yield[-1] >= _WATERMARK_PAGE_BATCH_SIZE

    def test_retry_documents_reuse_the_batched_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Out-of-band retry documents are indexed and counted like page docs."""
        # The watermark page holds doc 1; doc 2 is a previously-failed retry.
        paperless = make_reconciler_paperless(
            documents=[make_paperless_document(doc_id=1)]
        )
        paperless.document_exists.return_value = True
        paperless.get_document.return_value = make_paperless_document(doc_id=2)
        store_writer = make_reconciler_store_writer()
        store_writer._meta["failed_documents"] = '{"2": 1}'

        indexed_ids: list[int] = []

        def _index_document(
            _self: object, doc: dict, existing: IndexState | None
        ) -> IndexOutcome:
            indexed_ids.append(doc["id"])
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert sorted(indexed_ids) == [1, 2]
        assert report.indexed == 2


class TestSacredInvariantsBaseline:
    """The SHA-256 hash gate decides embed vs metadata-only.

    An unchanged ``modified`` is skipped without a fetch or embed; an advanced
    ``modified`` with identical content is fetched, hash-gated and routed to
    ``update_metadata``.
    """

    def test_unchanged_content_is_never_reembedded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        content = "Stable content body."
        modified = "2024-06-01T12:00:00+00:00"
        doc = make_paperless_document(doc_id=5, content=content, modified=modified)
        paperless = _light_paperless(
            full_docs=[doc], light_rows=[{"id": 5, "modified": modified}]
        )
        index_state = {
            5: IndexState(
                modified=normalise_paperless_timestamp(modified),
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark=modified, index_state=index_state
        )

        embedded: list[int] = []

        def _index_document(
            _self: object, d: dict, existing: IndexState | None
        ) -> IndexOutcome:
            # Mirrors the real worker's gate.
            doc_hash = hashlib.sha256(d["content"].encode()).hexdigest()
            if existing is not None and existing.content_hash == doc_hash:
                return IndexOutcome.METADATA_ONLY
            embedded.append(d["id"])
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert embedded == []
        paperless.get_document.assert_not_called()
        assert report.indexed == 0
        assert report.metadata_only == 0  # skipped, not even a metadata write

    def test_metadata_only_change_takes_the_no_embed_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        content = "Identical content."
        old_modified = "2024-06-01T00:00:00+00:00"
        new_modified = "2024-07-01T00:00:00+00:00"
        doc = make_paperless_document(doc_id=6, content=content, modified=new_modified)
        paperless = _light_paperless(
            full_docs=[doc], light_rows=[{"id": 6, "modified": new_modified}]
        )
        index_state = {
            6: IndexState(
                modified=normalise_paperless_timestamp(old_modified),
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark="2024-05-01T00:00:00+00:00", index_state=index_state
        )

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            _hash_gated_index_document,
        )

        report = run_incremental_sync(paperless, store_writer)

        paperless.get_document.assert_called_once_with(6)  # fetched lazily
        assert report.metadata_only == 1
        assert report.indexed == 0


def _light_paperless(*, full_docs: list[dict], light_rows: list[dict]) -> MagicMock:
    """A Paperless mock that pages light ``{id, modified}`` rows when a ``fields``
    projection is requested, and serves full documents from ``get_document``."""
    paperless = MagicMock()
    by_id = {doc["id"]: doc for doc in full_docs}

    def _iter(**kwargs: object) -> list[dict]:
        if "modified_after" not in kwargs:
            # Deletion-sweep style call (no incremental keyword) — ids only.
            return [{"id": doc_id} for doc_id in by_id]
        if kwargs.get("fields") is not None:
            return list(light_rows)
        return list(full_docs)

    paperless.iter_all_documents.side_effect = _iter
    paperless.get_document.side_effect = lambda doc_id: by_id[doc_id]
    paperless.document_exists.return_value = True
    paperless.list_correspondents.return_value = []
    paperless.list_document_types.return_value = []
    paperless.list_tags.return_value = []
    return paperless


class TestSteadyStateLightDiff:
    """In steady state, unchanged re-entered documents are skipped cold."""

    def test_steady_state_skip_never_embeds_or_fetches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        modified = "2024-06-01T12:00:00+00:00"
        full = make_paperless_document(doc_id=7, content="x", modified=modified)
        paperless = _light_paperless(
            full_docs=[full], light_rows=[{"id": 7, "modified": modified}]
        )
        from common.clock import normalise_paperless_timestamp

        index_state = {
            7: IndexState(
                modified=normalise_paperless_timestamp(modified),
                content_hash="whatever",
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark=modified, index_state=index_state
        )

        calls: list[int] = []

        def _index_document(
            _self: object, d: dict, existing: IndexState | None
        ) -> IndexOutcome:
            calls.append(d["id"])
            return IndexOutcome.INDEXED

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", _index_document
        )

        report = run_incremental_sync(paperless, store_writer)

        assert calls == []
        paperless.get_document.assert_not_called()
        assert report.indexed == 0
        assert report.metadata_only == 0

    def test_changed_modified_same_content_is_metadata_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        content = "Identical body."
        old_modified = "2024-06-01T00:00:00+00:00"
        new_modified = "2024-07-01T00:00:00+00:00"
        full = make_paperless_document(doc_id=8, content=content, modified=new_modified)
        paperless = _light_paperless(
            full_docs=[full], light_rows=[{"id": 8, "modified": new_modified}]
        )
        from common.clock import normalise_paperless_timestamp

        index_state = {
            8: IndexState(
                modified=normalise_paperless_timestamp(old_modified),
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark="2024-05-01T00:00:00+00:00", index_state=index_state
        )

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            _hash_gated_index_document,
        )

        report = run_incremental_sync(paperless, store_writer)

        paperless.get_document.assert_called_once_with(8)  # fetched lazily
        assert report.metadata_only == 1
        assert report.indexed == 0


class TestFirstRunBackfillGuard:
    """First-run backfill keeps the full-document page path."""

    def test_first_run_backfill_pages_full_documents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs = [make_paperless_document(doc_id=i) for i in (1, 2)]
        paperless = make_reconciler_paperless(documents=docs)
        store_writer = make_reconciler_store_writer(watermark=None)

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        report = run_incremental_sync(paperless, store_writer)

        incremental = [
            call
            for call in paperless.iter_all_documents.call_args_list
            if "modified_after" in call.kwargs
        ]
        assert len(incremental) == 1
        assert incremental[0].kwargs.get("fields") is None
        paperless.get_document.assert_not_called()
        assert report.indexed == 2


class TestLightDiffIsFailSafe:
    """An unrecognisable modified format degrades to a full fetch, never a skip."""

    def test_unrecognised_modified_format_falls_back_to_full_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        content = "Body."
        full = make_paperless_document(
            doc_id=9, content=content, modified="2024-06-01T00:00:00+00:00"
        )
        # The normaliser keeps a garbage modified verbatim, so it never equals
        # the store's normalised value.
        paperless = _light_paperless(
            full_docs=[full], light_rows=[{"id": 9, "modified": "not-a-timestamp"}]
        )
        index_state = {
            9: IndexState(
                modified="2024-06-01T00:00:00+00:00",
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark="2024-05-01T00:00:00+00:00", index_state=index_state
        )

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document",
            _hash_gated_index_document,
        )

        report = run_incremental_sync(paperless, store_writer)

        paperless.get_document.assert_called_once_with(9)
        assert report.metadata_only == 1


class TestSkipStillAdvancesWatermark:
    """A cycle that skips every document still advances the watermark."""

    def test_skipped_documents_still_advance_the_watermark(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from common.clock import normalise_paperless_timestamp

        modified = "2024-06-10T08:30:00+00:00"
        full = make_paperless_document(doc_id=10, content="x", modified=modified)
        paperless = _light_paperless(
            full_docs=[full], light_rows=[{"id": 10, "modified": modified}]
        )
        index_state = {
            10: IndexState(
                modified=normalise_paperless_timestamp(modified),
                content_hash="h",
            )
        }
        store_writer = make_reconciler_store_writer(
            watermark="2024-05-01T00:00:00+00:00", index_state=index_state
        )

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        run_incremental_sync(paperless, store_writer)

        expected = (datetime.fromisoformat(modified) - OVERLAP_MARGIN).isoformat()
        assert store_writer._meta["modified_watermark"] == expected


class TestChangedFetchFailureIsolated:
    """A get_document failure for one changed id is isolated."""

    def test_changed_document_fetch_failure_is_isolated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from common.paperless import PAPERLESS_CALL_EXCEPTIONS  # noqa: F401

        good = make_paperless_document(
            doc_id=11, content="a", modified="2024-07-01T00:00:00+00:00"
        )
        # Both ids have an advanced modified, so both are fetched.
        paperless = _light_paperless(
            full_docs=[good],
            light_rows=[
                {"id": 11, "modified": "2024-07-01T00:00:00+00:00"},
                {"id": 12, "modified": "2024-07-02T00:00:00+00:00"},
            ],
        )

        def _get_document(doc_id: int) -> dict:
            if doc_id == 12:
                raise ConnectionError("Paperless dropped fetching doc 12")
            return good

        paperless.get_document.side_effect = _get_document
        store_writer = make_reconciler_store_writer(
            watermark="2024-05-01T00:00:00+00:00", index_state={}
        )

        monkeypatch.setattr(
            "indexer.worker.DocumentIndexer.index_document", always_indexed
        )

        report = run_incremental_sync(paperless, store_writer)

        assert report.indexed == 1
        assert report.failed == 1


class TestIsUnchangedPredicate:
    """The skip predicate matches only on equal NORMALISED modified values."""

    def test_equal_after_normalisation_is_unchanged(self) -> None:
        from common.clock import normalise_paperless_timestamp
        from indexer.reconciler._light_diff import _is_unchanged

        existing = IndexState(
            modified=normalise_paperless_timestamp("2024-06-01T12:00:00Z"),
            content_hash="h",
        )
        # A different wire format for the same instant.
        assert _is_unchanged(existing, "2024-06-01T12:00:00+00:00") is True

    def test_different_instant_is_not_unchanged(self) -> None:
        from common.clock import normalise_paperless_timestamp
        from indexer.reconciler._light_diff import _is_unchanged

        existing = IndexState(
            modified=normalise_paperless_timestamp("2024-06-01T12:00:00Z"),
            content_hash="h",
        )
        assert _is_unchanged(existing, "2024-07-01T00:00:00+00:00") is False

    def test_none_existing_is_not_unchanged(self) -> None:
        from indexer.reconciler._light_diff import _is_unchanged

        assert _is_unchanged(None, "2024-06-01T12:00:00+00:00") is False

    def test_unparseable_projected_modified_is_not_unchanged(self) -> None:
        from indexer.reconciler._light_diff import _is_unchanged

        existing = IndexState(modified="2024-06-01T12:00:00+00:00", content_hash="h")
        assert _is_unchanged(existing, "not-a-timestamp") is False
