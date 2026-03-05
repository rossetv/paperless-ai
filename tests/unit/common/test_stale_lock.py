"""
Unit tests for common.stale_lock.recover_stale_locks.

Tests cover: skip conditions, single/multi document recovery, error handling,
non-integer doc IDs, and return count.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from common.stale_lock import recover_stale_locks


class TestRecoverStaleLocks:
    """Tests for recover_stale_locks()."""

    def test_returns_zero_when_processing_tag_id_is_none(self):
        # Arrange
        client = MagicMock()

        # Act
        result = recover_stale_locks(client, processing_tag_id=None, pre_tag_id=1)

        # Assert
        assert result == 0
        client.get_documents_by_tag.assert_not_called()

    def test_returns_zero_when_processing_tag_id_is_zero(self):
        # Arrange
        client = MagicMock()

        # Act
        result = recover_stale_locks(client, processing_tag_id=0, pre_tag_id=1)

        # Assert
        assert result == 0
        client.get_documents_by_tag.assert_not_called()

    def test_recovers_single_stale_document(self):
        # Arrange
        client = MagicMock()
        processing_tag = 50
        pre_tag = 10
        doc = {"id": 1, "tags": [50, 99]}
        client.get_documents_by_tag.return_value = [doc]

        # Act
        result = recover_stale_locks(
            client, processing_tag_id=processing_tag, pre_tag_id=pre_tag,
        )

        # Assert
        assert result == 1
        call_args = client.update_document_metadata.call_args
        updated_tags = set(call_args.kwargs["tags"])
        assert processing_tag not in updated_tags
        assert pre_tag in updated_tags
        assert 99 in updated_tags

    def test_recovers_multiple_documents(self):
        # Arrange
        client = MagicMock()
        processing_tag = 50
        pre_tag = 10
        docs = [
            {"id": 1, "tags": [50, 100]},
            {"id": 2, "tags": [50, 200]},
            {"id": 3, "tags": [50, 300]},
        ]
        client.get_documents_by_tag.return_value = docs

        # Act
        result = recover_stale_locks(
            client, processing_tag_id=processing_tag, pre_tag_id=pre_tag,
        )

        # Assert
        assert result == 3
        assert client.update_document_metadata.call_count == 3

    def test_handles_query_failure_gracefully(self):
        # Arrange
        client = MagicMock()
        client.get_documents_by_tag.side_effect = ConnectionError("API down")

        # Act
        result = recover_stale_locks(
            client, processing_tag_id=50, pre_tag_id=10,
        )

        # Assert
        assert result == 0

    def test_handles_single_doc_update_failure_continues_with_rest(self):
        # Arrange
        client = MagicMock()
        docs = [
            {"id": 1, "tags": [50]},
            {"id": 2, "tags": [50]},
            {"id": 3, "tags": [50]},
        ]
        client.get_documents_by_tag.return_value = docs
        # Second document fails
        client.update_document_metadata.side_effect = [
            None,                           # doc 1 OK
            ConnectionError("update failed"),  # doc 2 fails
            None,                           # doc 3 OK
        ]

        # Act
        result = recover_stale_locks(
            client, processing_tag_id=50, pre_tag_id=10,
        )

        # Assert
        assert result == 2  # only doc 1 and doc 3 counted
        assert client.update_document_metadata.call_count == 3

    def test_skips_documents_without_integer_id(self):
        # Arrange
        client = MagicMock()
        docs = [
            {"id": "not-an-int", "tags": [50]},
            {"tags": [50]},  # no id at all
            {"id": None, "tags": [50]},
        ]
        client.get_documents_by_tag.return_value = docs

        # Act
        result = recover_stale_locks(
            client, processing_tag_id=50, pre_tag_id=10,
        )

        # Assert
        assert result == 0
        client.update_document_metadata.assert_not_called()

    def test_returns_count_of_recovered_documents(self):
        # Arrange
        client = MagicMock()
        docs = [
            {"id": 1, "tags": [50]},
            {"id": 2, "tags": [50]},
        ]
        client.get_documents_by_tag.return_value = docs

        # Act
        result = recover_stale_locks(
            client, processing_tag_id=50, pre_tag_id=10,
        )

        # Assert
        assert result == 2
