"""Tests for indexer.worker.DocumentIndexer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from indexer.worker import DocumentIndexer, IndexOutcome
from store.models import IndexState
from tests.helpers.factories import make_paperless_document, make_settings_obj
from tests.helpers.mocks import make_mock_embedding_client

# make_settings_obj() defaults to ERROR_TAG_ID=552, CHUNK_SIZE=2000 and
# CHUNK_OVERLAP=256.

_DEFAULT_DOC_CONTENT = "This is a test document with enough text to be chunked."


def _make_doc(**overrides: Any) -> dict:
    """Build a Paperless document whose default content is long enough to chunk."""
    overrides.setdefault("content", _DEFAULT_DOC_CONTENT)
    return make_paperless_document(**overrides)


class TestGateEmptyContent:
    """Documents with empty or whitespace-only content are skipped."""

    def test_empty_content_returns_skipped(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, store_writer, embedding_client)

        doc = _make_doc(content="")
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.SKIPPED
        embedding_client.embed.assert_not_called()
        store_writer.upsert_document.assert_not_called()
        store_writer.update_metadata.assert_not_called()

    def test_whitespace_content_returns_skipped(self) -> None:
        settings = make_settings_obj()
        indexer = DocumentIndexer(settings, MagicMock(), make_mock_embedding_client())

        doc = _make_doc(content="   \n\t  ")
        assert indexer.index_document(doc, existing=None) is IndexOutcome.SKIPPED

    def test_none_content_returns_skipped(self) -> None:
        """Paperless may return null content for un-OCR'd documents."""
        settings = make_settings_obj()
        indexer = DocumentIndexer(settings, MagicMock(), make_mock_embedding_client())

        doc = _make_doc(content=None)
        assert indexer.index_document(doc, existing=None) is IndexOutcome.SKIPPED


class TestGateErrorTag:
    """Documents carrying the ERROR_TAG_ID are skipped."""

    def test_error_tagged_document_returns_skipped(self) -> None:
        settings = make_settings_obj(ERROR_TAG_ID=552)
        store_writer = MagicMock()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, store_writer, embedding_client)

        doc = _make_doc(tags=[10, 552, 20])
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.SKIPPED
        embedding_client.embed.assert_not_called()
        store_writer.upsert_document.assert_not_called()

    def test_error_tag_id_none_means_gate_disabled(self) -> None:
        settings = make_settings_obj(ERROR_TAG_ID=None)
        store_writer = MagicMock()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, store_writer, embedding_client)

        doc = _make_doc(tags=[552])
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.INDEXED
        store_writer.upsert_document.assert_called_once()


class TestGatePrunesStaleDocument:
    """A document that was indexed but is now un-indexable has its rows pruned.

    The document still exists in Paperless, so the deletion sweep never reaches
    it; without the prune, search keeps serving its stale chunks.
    """

    def _existing_state(self) -> IndexState:
        """A store row standing for a previously-indexed document."""
        return IndexState(
            modified="2024-05-01T00:00:00+00:00",
            content_hash="some_previously_indexed_hash",
        )

    def test_emptied_content_prunes_the_previously_indexed_document(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, store_writer, embedding_client)

        doc = _make_doc(content="")
        outcome = indexer.index_document(doc, existing=self._existing_state())

        assert outcome is IndexOutcome.SKIPPED
        embedding_client.embed.assert_not_called()
        store_writer.upsert_document.assert_not_called()
        store_writer.update_metadata.assert_not_called()
        store_writer.delete_documents.assert_called_once_with((doc["id"],))

    def test_error_tagged_after_indexing_prunes_the_document(self) -> None:
        settings = make_settings_obj(ERROR_TAG_ID=552)
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())

        doc = _make_doc(tags=[10, 552])
        outcome = indexer.index_document(doc, existing=self._existing_state())

        assert outcome is IndexOutcome.SKIPPED
        store_writer.delete_documents.assert_called_once_with((doc["id"],))

    def test_never_indexed_unindexable_document_is_not_pruned(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())

        doc = _make_doc(content="")
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.SKIPPED
        store_writer.delete_documents.assert_not_called()


class TestNewDocument:
    """A document with no existing IndexState follows the full embed + upsert path."""

    def test_new_document_returns_indexed(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, store_writer, embedding_client)

        doc = _make_doc()
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.INDEXED

    def test_new_document_calls_embed(self) -> None:
        settings = make_settings_obj()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, MagicMock(), embedding_client)

        doc = _make_doc()
        indexer.index_document(doc, existing=None)

        embedding_client.embed.assert_called_once()

    def test_new_document_calls_upsert_document(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())

        doc = _make_doc()
        indexer.index_document(doc, existing=None)

        store_writer.upsert_document.assert_called_once()
        store_writer.update_metadata.assert_not_called()


class TestUnchangedHash:
    """When content hash is unchanged, only metadata is updated — no re-embed."""

    def _existing_state_for(self, doc: dict) -> IndexState:
        """Build an IndexState whose content_hash matches the doc's content."""
        import hashlib

        content_hash = hashlib.sha256(doc["content"].encode()).hexdigest()
        return IndexState(
            modified="2024-05-01T00:00:00+00:00",
            content_hash=content_hash,
        )

    def test_unchanged_hash_returns_metadata_only(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, store_writer, embedding_client)

        doc = _make_doc()
        existing = self._existing_state_for(doc)
        outcome = indexer.index_document(doc, existing=existing)

        assert outcome is IndexOutcome.METADATA_ONLY

    def test_unchanged_hash_does_not_call_embed(self) -> None:
        settings = make_settings_obj()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, MagicMock(), embedding_client)

        doc = _make_doc()
        existing = self._existing_state_for(doc)
        indexer.index_document(doc, existing=existing)

        embedding_client.embed.assert_not_called()

    def test_unchanged_hash_calls_update_metadata(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())

        doc = _make_doc()
        existing = self._existing_state_for(doc)
        indexer.index_document(doc, existing=existing)

        store_writer.update_metadata.assert_called_once()
        store_writer.upsert_document.assert_not_called()


class TestChangedHash:
    """When the content hash changes, the document is re-chunked and re-embedded."""

    def test_changed_hash_returns_indexed(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, store_writer, embedding_client)

        doc = _make_doc()
        existing = IndexState(
            modified="2024-05-01T00:00:00+00:00",
            content_hash="stale_hash_that_does_not_match",
        )
        outcome = indexer.index_document(doc, existing=existing)

        assert outcome is IndexOutcome.INDEXED

    def test_changed_hash_calls_embed(self) -> None:
        settings = make_settings_obj()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, MagicMock(), embedding_client)

        doc = _make_doc()
        existing = IndexState(
            modified="2024-05-01T00:00:00+00:00",
            content_hash="stale_hash_that_does_not_match",
        )
        indexer.index_document(doc, existing=existing)

        embedding_client.embed.assert_called_once()

    def test_changed_hash_calls_upsert_document(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())

        doc = _make_doc()
        existing = IndexState(
            modified="2024-05-01T00:00:00+00:00",
            content_hash="stale_hash_that_does_not_match",
        )
        indexer.index_document(doc, existing=existing)

        store_writer.upsert_document.assert_called_once()
        store_writer.update_metadata.assert_not_called()


class TestDateNormalisation:
    """created and modified are normalised to UTC ISO-8601 in DocumentMeta."""

    def _capture_meta(self, doc: dict) -> "MagicMock":
        """Run index_document and return the DocumentMeta passed to upsert_document."""
        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())
        indexer.index_document(doc, existing=None)
        # upsert_document(meta, chunks)
        return store_writer.upsert_document.call_args[0][0]

    def test_modified_utc_zulu_passthrough(self) -> None:
        doc = _make_doc(modified="2024-06-01T12:00:00+00:00")
        meta = self._capture_meta(doc)
        dt = datetime.fromisoformat(meta.modified)
        assert dt.tzinfo is not None
        assert (
            dt.utctimetuple()
            == datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc).utctimetuple()
        )

    def test_modified_offset_normalised_to_utc(self) -> None:
        doc = _make_doc(modified="2024-06-01T12:00:00+02:00")
        meta = self._capture_meta(doc)
        dt = datetime.fromisoformat(meta.modified)
        assert dt.tzinfo is not None
        assert (
            dt.utctimetuple()
            == datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc).utctimetuple()
        )

    def test_created_none_preserved(self) -> None:
        doc = _make_doc(created=None)
        meta = self._capture_meta(doc)
        assert meta.created is None

    def test_created_date_only_normalised_to_utc_iso8601(self) -> None:
        """A bare YYYY-MM-DD date becomes midnight UTC."""
        doc = _make_doc(created="2024-01-15")
        meta = self._capture_meta(doc)
        assert meta.created is not None
        dt = datetime.fromisoformat(meta.created)
        assert dt.tzinfo is not None
        assert dt.utctimetuple()[:3] == (2024, 1, 15)

    def test_created_datetime_with_offset_normalised(self) -> None:
        doc = _make_doc(created="2024-01-15T10:00:00+02:00")
        meta = self._capture_meta(doc)
        assert meta.created is not None
        dt = datetime.fromisoformat(meta.created)
        assert dt.tzinfo is not None
        assert (
            dt.utctimetuple()
            == datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc).utctimetuple()
        )

    def test_metadata_only_path_also_normalises_dates(self) -> None:
        import hashlib

        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())
        doc = _make_doc(
            content="Stable content.",
            modified="2024-06-01T12:00:00+02:00",
        )
        existing = IndexState(
            modified="2024-05-01T00:00:00+00:00",
            content_hash=hashlib.sha256(doc["content"].encode()).hexdigest(),
        )
        indexer.index_document(doc, existing=existing)

        meta = store_writer.update_metadata.call_args[0][0]
        dt = datetime.fromisoformat(meta.modified)
        assert dt.tzinfo is not None
        assert (
            dt.utctimetuple()
            == datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc).utctimetuple()
        )


class TestUnparseableDateIsLogged:
    """An unparseable Paperless date is stored verbatim and logged as a warning."""

    def _index_and_capture_logs(self, doc: dict) -> tuple[object, list[dict]]:
        """Index *doc* and return the captured DocumentMeta and log events."""
        import structlog.testing

        store_writer = MagicMock()
        indexer = DocumentIndexer(
            make_settings_obj(), store_writer, make_mock_embedding_client()
        )
        with structlog.testing.capture_logs() as captured:
            indexer.index_document(doc, existing=None)
        return store_writer.upsert_document.call_args[0][0], captured

    def test_unparseable_modified_is_kept_verbatim_and_logged(self) -> None:
        doc = _make_doc(modified="not-a-real-timestamp")
        meta, captured = self._index_and_capture_logs(doc)

        assert meta.modified == "not-a-real-timestamp"
        warnings = [
            event for event in captured if event["event"] == "worker.unparseable_date"
        ]
        assert len(warnings) == 1
        assert warnings[0]["log_level"] == "warning"
        assert warnings[0]["field"] == "modified"
        assert warnings[0]["value"] == "not-a-real-timestamp"

    def test_parseable_dates_log_no_warning(self) -> None:
        doc = _make_doc(created="2024-01-15", modified="2024-06-01T12:00:00+00:00")
        _, captured = self._index_and_capture_logs(doc)

        assert not [
            event for event in captured if event["event"] == "worker.unparseable_date"
        ]


# chunk_text strips OCR page markers, so marker-only content passes the
# whitespace gate but yields zero chunks. These tests use the real chunker.
_MARKERS_ONLY = "--- Page 1 ---\n--- Page 2 ---"


class TestZeroChunkGuard:
    """Content that passes the whitespace gate but yields zero chunks is skipped.

    A chunk-less documents row would store a content_hash that traps the
    document in METADATA_ONLY with no search results.
    """

    def test_marker_only_content_returns_skipped(self) -> None:
        settings = make_settings_obj()
        indexer = DocumentIndexer(settings, MagicMock(), make_mock_embedding_client())

        doc = _make_doc(content=_MARKERS_ONLY)
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.SKIPPED

    def test_marker_only_content_does_not_call_upsert(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, store_writer, embedding_client)

        doc = _make_doc(content=_MARKERS_ONLY)
        indexer.index_document(doc, existing=None)

        store_writer.upsert_document.assert_not_called()
        store_writer.update_metadata.assert_not_called()
        embedding_client.embed.assert_not_called()

    def test_marker_only_content_logs_warning(self) -> None:
        import structlog.testing

        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())

        doc = _make_doc(content=_MARKERS_ONLY)
        with structlog.testing.capture_logs() as captured:
            indexer.index_document(doc, existing=None)

        skipped_events = [
            e for e in captured if e["event"] == "worker.document_skipped"
        ]
        assert len(skipped_events) == 1
        assert skipped_events[0]["log_level"] == "warning"
        assert skipped_events[0]["reason"] == "indexed_content_produced_zero_chunks"

    def test_marker_only_new_document_does_not_delete(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())

        doc = _make_doc(content=_MARKERS_ONLY)
        indexer.index_document(doc, existing=None)

        store_writer.delete_documents.assert_not_called()

    def test_marker_only_previously_indexed_prunes_stale_row(self) -> None:
        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())

        doc = _make_doc(content=_MARKERS_ONLY)
        existing = IndexState(
            modified="2024-05-01T00:00:00+00:00",
            content_hash="some_previously_indexed_hash",
        )
        outcome = indexer.index_document(doc, existing=existing)

        assert outcome is IndexOutcome.SKIPPED
        store_writer.delete_documents.assert_called_once_with((doc["id"],))
        store_writer.upsert_document.assert_not_called()

    def test_future_cycle_with_real_content_can_be_indexed(self) -> None:
        """No hash is stored on the zero-chunk path, so the hash gate never fires."""
        settings = make_settings_obj()
        store_writer = MagicMock()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, store_writer, embedding_client)

        doc_cycle1 = _make_doc(content=_MARKERS_ONLY)
        outcome1 = indexer.index_document(doc_cycle1, existing=None)
        assert outcome1 is IndexOutcome.SKIPPED
        store_writer.upsert_document.assert_not_called()

        # existing=None because cycle 1 wrote nothing.
        doc_cycle2 = _make_doc(content=_DEFAULT_DOC_CONTENT)
        outcome2 = indexer.index_document(doc_cycle2, existing=None)
        assert outcome2 is IndexOutcome.INDEXED
        store_writer.upsert_document.assert_called_once()
