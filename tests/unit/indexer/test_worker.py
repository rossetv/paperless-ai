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
from unittest.mock import MagicMock, call

import pytest

from indexer.worker import DocumentIndexer, IndexOutcome
from store.models import IndexState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(
    *,
    error_tag_id: int | None = 552,
    chunk_size: int = 2000,
    chunk_overlap: int = 256,
) -> MagicMock:
    """Return a settings mock with the fields the worker reads."""
    settings = MagicMock()
    settings.ERROR_TAG_ID = error_tag_id
    settings.CHUNK_SIZE = chunk_size
    settings.CHUNK_OVERLAP = chunk_overlap
    return settings


def _make_store_writer() -> MagicMock:
    """Return a mock StoreWriter."""
    return MagicMock()


def _make_embedding_client(dimensions: int = 4) -> MagicMock:
    """Return a mock EmbeddingClient whose embed() returns deterministic vectors."""
    client = MagicMock()
    # embed() takes a list of texts and returns one vector per text.
    client.embed.side_effect = lambda texts: [
        [1.0 / (dimensions ** 0.5)] * dimensions for _ in texts
    ]
    return client


def _make_doc(
    *,
    doc_id: int = 1,
    content: str = "This is a test document with enough text to be chunked.",
    tags: list[int] | None = None,
    correspondent: int | None = None,
    document_type: int | None = None,
    created: str | None = "2024-01-15T10:00:00+00:00",
    modified: str = "2024-06-01T12:00:00+00:00",
    title: str = "Test Document",
) -> dict:
    """Build a minimal Paperless document dict."""
    return {
        "id": doc_id,
        "title": title,
        "content": content,
        "tags": tags if tags is not None else [10, 20],
        "correspondent": correspondent,
        "document_type": document_type,
        "created": created,
        "modified": modified,
    }


# ---------------------------------------------------------------------------
# Gate: empty content
# ---------------------------------------------------------------------------

class TestGateEmptyContent:
    """Documents with empty or whitespace-only content are skipped."""

    def test_empty_content_returns_skipped(self) -> None:
        settings = _make_settings()
        store_writer = _make_store_writer()
        embedding_client = _make_embedding_client()
        indexer = DocumentIndexer(
            settings, store_writer, embedding_client
        )

        doc = _make_doc(content="")
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.SKIPPED
        embedding_client.embed.assert_not_called()
        store_writer.upsert_document.assert_not_called()
        store_writer.update_metadata.assert_not_called()

    def test_whitespace_content_returns_skipped(self) -> None:
        settings = _make_settings()
        indexer = DocumentIndexer(
            settings, _make_store_writer(), _make_embedding_client()
        )

        doc = _make_doc(content="   \n\t  ")
        assert indexer.index_document(doc, existing=None) is IndexOutcome.SKIPPED

    def test_none_content_returns_skipped(self) -> None:
        """Paperless may return null content for un-OCR'd documents."""
        settings = _make_settings()
        indexer = DocumentIndexer(
            settings, _make_store_writer(), _make_embedding_client()
        )

        doc = _make_doc(content=None)  # type: ignore[arg-type]
        assert indexer.index_document(doc, existing=None) is IndexOutcome.SKIPPED


# ---------------------------------------------------------------------------
# Gate: error tag
# ---------------------------------------------------------------------------

class TestGateErrorTag:
    """Documents carrying the ERROR_TAG_ID are skipped."""

    def test_error_tagged_document_returns_skipped(self) -> None:
        settings = _make_settings(error_tag_id=552)
        store_writer = _make_store_writer()
        embedding_client = _make_embedding_client()
        indexer = DocumentIndexer(
            settings, store_writer, embedding_client
        )

        doc = _make_doc(tags=[10, 552, 20])
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.SKIPPED
        embedding_client.embed.assert_not_called()
        store_writer.upsert_document.assert_not_called()

    def test_error_tag_id_none_means_gate_disabled(self) -> None:
        """When ERROR_TAG_ID is None the gate cannot trigger; document is indexed."""
        settings = _make_settings(error_tag_id=None)
        store_writer = _make_store_writer()
        embedding_client = _make_embedding_client()
        indexer = DocumentIndexer(
            settings, store_writer, embedding_client
        )

        doc = _make_doc(tags=[552])
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.INDEXED
        store_writer.upsert_document.assert_called_once()


# ---------------------------------------------------------------------------
# New document: full index path
# ---------------------------------------------------------------------------

class TestNewDocument:
    """A document with no existing IndexState follows the full embed + upsert path."""

    def test_new_document_returns_indexed(self) -> None:
        settings = _make_settings()
        store_writer = _make_store_writer()
        embedding_client = _make_embedding_client()
        indexer = DocumentIndexer(
            settings, store_writer, embedding_client
        )

        doc = _make_doc()
        outcome = indexer.index_document(doc, existing=None)

        assert outcome is IndexOutcome.INDEXED

    def test_new_document_calls_embed(self) -> None:
        settings = _make_settings()
        embedding_client = _make_embedding_client()
        indexer = DocumentIndexer(
            settings, _make_store_writer(), embedding_client
        )

        doc = _make_doc()
        indexer.index_document(doc, existing=None)

        embedding_client.embed.assert_called_once()

    def test_new_document_calls_upsert_document(self) -> None:
        settings = _make_settings()
        store_writer = _make_store_writer()
        indexer = DocumentIndexer(
            settings, store_writer, _make_embedding_client()
        )

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
        settings = _make_settings()
        store_writer = _make_store_writer()
        embedding_client = _make_embedding_client()
        indexer = DocumentIndexer(
            settings, store_writer, embedding_client
        )

        doc = _make_doc()
        existing = self._existing_state_for(doc)
        outcome = indexer.index_document(doc, existing=existing)

        assert outcome is IndexOutcome.METADATA_ONLY

    def test_unchanged_hash_does_not_call_embed(self) -> None:
        settings = _make_settings()
        embedding_client = _make_embedding_client()
        indexer = DocumentIndexer(
            settings, _make_store_writer(), embedding_client
        )

        doc = _make_doc()
        existing = self._existing_state_for(doc)
        indexer.index_document(doc, existing=existing)

        embedding_client.embed.assert_not_called()

    def test_unchanged_hash_calls_update_metadata(self) -> None:
        settings = _make_settings()
        store_writer = _make_store_writer()
        indexer = DocumentIndexer(
            settings, store_writer, _make_embedding_client()
        )

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
        settings = _make_settings()
        store_writer = _make_store_writer()
        embedding_client = _make_embedding_client()
        indexer = DocumentIndexer(
            settings, store_writer, embedding_client
        )

        doc = _make_doc()
        existing = IndexState(
            modified="2024-05-01T00:00:00+00:00",
            content_hash="stale_hash_that_does_not_match",
        )
        outcome = indexer.index_document(doc, existing=existing)

        assert outcome is IndexOutcome.INDEXED

    def test_changed_hash_calls_embed(self) -> None:
        settings = _make_settings()
        embedding_client = _make_embedding_client()
        indexer = DocumentIndexer(
            settings, _make_store_writer(), embedding_client
        )

        doc = _make_doc()
        existing = IndexState(
            modified="2024-05-01T00:00:00+00:00",
            content_hash="stale_hash_that_does_not_match",
        )
        indexer.index_document(doc, existing=existing)

        embedding_client.embed.assert_called_once()

    def test_changed_hash_calls_upsert_document(self) -> None:
        settings = _make_settings()
        store_writer = _make_store_writer()
        indexer = DocumentIndexer(
            settings, store_writer, _make_embedding_client()
        )

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
        settings = _make_settings()
        store_writer = _make_store_writer()
        indexer = DocumentIndexer(
            settings, store_writer, _make_embedding_client()
        )
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
        assert dt.utctimetuple() == datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc).utctimetuple()

    def test_modified_offset_normalised_to_utc(self) -> None:
        """A modified value with a non-UTC offset is converted to UTC."""
        # +02:00 → 10:00 UTC
        doc = _make_doc(modified="2024-06-01T12:00:00+02:00")
        meta = self._capture_meta(doc)
        dt = datetime.fromisoformat(meta.modified)
        assert dt.tzinfo is not None
        # 12:00 +02:00 = 10:00 UTC
        assert dt.utctimetuple() == datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc).utctimetuple()

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
        assert dt.utctimetuple() == datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc).utctimetuple()

    def test_metadata_only_path_also_normalises_dates(self) -> None:
        """Date normalisation applies on the METADATA_ONLY path too."""
        import hashlib

        settings = _make_settings()
        store_writer = _make_store_writer()
        indexer = DocumentIndexer(
            settings, store_writer, _make_embedding_client()
        )
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
        assert dt.utctimetuple() == datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc).utctimetuple()
