"""Tests for indexer.worker.DocumentIndexer.

Verifies the per-document indexing pipeline:
- Gate: empty content → SKIPPED; error-tagged document → SKIPPED.
- New document (no existing IndexState) → INDEXED (embed + upsert called).
- Content unchanged (existing IndexState, same hash) → METADATA_ONLY
  (embed NOT called, update_metadata called).
- Content changed (existing IndexState, different hash) → INDEXED (re-embedded).
- created/modified fields are normalised to UTC ISO-8601 in DocumentMeta.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from indexer.worker import DocumentIndexer, IndexOutcome
from store.models import IndexState
from tests.helpers.factories import make_paperless_document, make_settings_obj
from tests.helpers.mocks import make_mock_embedding_client

# Settings, the embedding client, and Paperless documents all come from the
# shared factories (CODE_GUIDELINES §11.5).  make_settings_obj()'s defaults
# already match what the worker reads — ERROR_TAG_ID=552, CHUNK_SIZE=2000,
# CHUNK_OVERLAP=256 — so the no-argument case needs no overrides.

_DEFAULT_DOC_CONTENT = "This is a test document with enough text to be chunked."


def _make_doc(**overrides: Any) -> dict:
    """Build a Paperless document with a worker-friendly default content body.

    A thin wrapper over :func:`~tests.helpers.factories.make_paperless_document`
    that defaults ``content`` to text long enough to chunk; the indexer-shaped
    document is otherwise the shared factory's.
    """
    overrides.setdefault("content", _DEFAULT_DOC_CONTENT)
    return make_paperless_document(**overrides)


# ---------------------------------------------------------------------------
# Gate: empty content
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Gate: error tag
# ---------------------------------------------------------------------------


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
        """When ERROR_TAG_ID is None the gate cannot trigger; document is indexed."""
        settings = make_settings_obj(ERROR_TAG_ID=None)
        store_writer = MagicMock()
        embedding_client = make_mock_embedding_client()
        indexer = DocumentIndexer(settings, store_writer, embedding_client)

        doc = _make_doc(tags=[552])
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.INDEXED
        store_writer.upsert_document.assert_called_once()


# ---------------------------------------------------------------------------
# Gate: a previously-indexed document that became un-indexable is pruned
# ---------------------------------------------------------------------------


class TestGatePrunesStaleDocument:
    """A document that was indexed but is now un-indexable has its rows pruned.

    IDX-01: when the OCR content is emptied, or the error tag is applied, *after*
    the document was indexed, the worker must delete its stale rows from the
    store rather than silently SKIPPED — otherwise search keeps serving chunks
    for content that no longer exists, and the deletion sweep cannot reach it
    (the document still exists in Paperless).
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
        # The stale rows must be pruned.
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
        """No existing row → SKIPPED is a pure no-op; nothing is deleted."""
        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())

        doc = _make_doc(content="")
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.SKIPPED
        store_writer.delete_documents.assert_not_called()


# ---------------------------------------------------------------------------
# New document: full index path
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Unchanged hash: metadata-only path
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Changed hash: re-index path
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------


class TestDateNormalisation:
    """created and modified are normalised to UTC ISO-8601 in DocumentMeta."""

    def _capture_meta(self, doc: dict) -> "MagicMock":
        """Run index_document and return the DocumentMeta passed to upsert_document."""
        settings = make_settings_obj()
        store_writer = MagicMock()
        indexer = DocumentIndexer(settings, store_writer, make_mock_embedding_client())
        indexer.index_document(doc, existing=None)
        # upsert_document is called as upsert_document(meta, chunks)
        return store_writer.upsert_document.call_args[0][0]

    def test_modified_utc_zulu_passthrough(self) -> None:
        """An already-UTC modified value is stored as an ISO-8601 string."""
        doc = _make_doc(modified="2024-06-01T12:00:00+00:00")
        meta = self._capture_meta(doc)
        # Must be a valid ISO-8601 UTC string; exact format is normalised by
        # datetime.fromisoformat + isoformat.
        dt = datetime.fromisoformat(meta.modified)
        assert dt.tzinfo is not None
        assert (
            dt.utctimetuple()
            == datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc).utctimetuple()
        )

    def test_modified_offset_normalised_to_utc(self) -> None:
        """A modified value with a non-UTC offset is converted to UTC."""
        # +02:00 → 10:00 UTC
        doc = _make_doc(modified="2024-06-01T12:00:00+02:00")
        meta = self._capture_meta(doc)
        dt = datetime.fromisoformat(meta.modified)
        assert dt.tzinfo is not None
        # 12:00 +02:00 = 10:00 UTC
        assert (
            dt.utctimetuple()
            == datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc).utctimetuple()
        )

    def test_created_none_preserved(self) -> None:
        """A None created date is stored as None."""
        doc = _make_doc(created=None)
        meta = self._capture_meta(doc)
        assert meta.created is None

    def test_created_date_only_normalised_to_utc_iso8601(self) -> None:
        """A bare date string (YYYY-MM-DD) is normalised to midnight UTC ISO-8601."""
        doc = _make_doc(created="2024-01-15")
        meta = self._capture_meta(doc)
        assert meta.created is not None
        dt = datetime.fromisoformat(meta.created)
        # Must be UTC-aware and at midnight
        assert dt.tzinfo is not None
        assert dt.utctimetuple()[:3] == (2024, 1, 15)

    def test_created_datetime_with_offset_normalised(self) -> None:
        """A created datetime with timezone offset is normalised to UTC."""
        doc = _make_doc(created="2024-01-15T10:00:00+02:00")
        meta = self._capture_meta(doc)
        assert meta.created is not None
        dt = datetime.fromisoformat(meta.created)
        assert dt.tzinfo is not None
        # 10:00 +02:00 = 08:00 UTC
        assert (
            dt.utctimetuple()
            == datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc).utctimetuple()
        )

    def test_metadata_only_path_also_normalises_dates(self) -> None:
        """Date normalisation applies on the METADATA_ONLY path too."""
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


# ---------------------------------------------------------------------------
# Unparseable dates are logged, not silently swallowed
# ---------------------------------------------------------------------------


class TestUnparseableDateIsLogged:
    """A Paperless date that does not parse is stored verbatim AND logged.

    An unparseable upstream timestamp is a recoverable anomaly: the worker
    keeps the value rather than dropping the field, but it must surface a
    WARNING so the operator can see the bad data (SPEC §4.1, §7.3).
    """

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

        # The value is stored verbatim — the field is not dropped.
        assert meta.modified == "not-a-real-timestamp"
        # A WARNING names the document, the field, and the offending value.
        warnings = [
            event for event in captured if event["event"] == "worker.unparseable_date"
        ]
        assert len(warnings) == 1
        assert warnings[0]["log_level"] == "warning"
        assert warnings[0]["field"] == "modified"
        assert warnings[0]["value"] == "not-a-real-timestamp"

    def test_parseable_dates_log_no_warning(self) -> None:
        """A document with valid dates produces no unparseable-date warning."""
        doc = _make_doc(created="2024-01-15", modified="2024-06-01T12:00:00+00:00")
        _, captured = self._index_and_capture_logs(doc)

        assert not [
            event for event in captured if event["event"] == "worker.unparseable_date"
        ]
