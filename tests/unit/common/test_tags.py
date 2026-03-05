"""
Unit tests for common.tags module.

Tests cover: extract_tags, get_latest_tags, remove_stale_queue_tag,
release_processing_tag, and clean_pipeline_tags.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from common.tags import (
    clean_pipeline_tags,
    extract_tags,
    get_latest_tags,
    release_processing_tag,
    remove_stale_queue_tag,
)
from tests.helpers.factories import make_settings_obj


# ---------------------------------------------------------------------------
# extract_tags
# ---------------------------------------------------------------------------

class TestExtractTags:
    """Tests for extract_tags()."""

    def test_returns_set_of_ints_from_doc_tags(self):
        # Arrange
        doc = {"tags": [1, 2, 3]}

        # Act
        result = extract_tags(doc, doc_id=1, context="test")

        # Assert
        assert result == {1, 2, 3}

    def test_returns_empty_set_when_tags_key_missing(self):
        # Arrange
        doc = {"id": 1, "title": "No tags key"}

        # Act
        result = extract_tags(doc, doc_id=1, context="test")

        # Assert
        assert result == set()

    def test_returns_empty_set_when_tags_is_none(self):
        # Arrange
        doc = {"tags": None}

        # Act
        result = extract_tags(doc, doc_id=1, context="test")

        # Assert
        assert result == set()

    def test_returns_empty_set_when_tags_is_not_a_list(self):
        # Arrange
        doc = {"tags": "not-a-list"}

        # Act
        result = extract_tags(doc, doc_id=1, context="test")

        # Assert
        assert result == set()

    def test_handles_empty_list(self):
        # Arrange
        doc = {"tags": []}

        # Act
        result = extract_tags(doc, doc_id=1, context="test")

        # Assert
        assert result == set()

    def test_returns_set_preserving_unique_ids(self):
        # Arrange
        doc = {"tags": [5, 5, 10]}

        # Act
        result = extract_tags(doc, doc_id=1, context="test")

        # Assert
        assert result == {5, 10}


# ---------------------------------------------------------------------------
# get_latest_tags
# ---------------------------------------------------------------------------

class TestGetLatestTags:
    """Tests for get_latest_tags()."""

    def test_fetches_fresh_document_and_extracts_tags(self):
        # Arrange
        client = MagicMock()
        client.get_document.return_value = {"tags": [10, 20]}

        # Act
        result = get_latest_tags(client, doc_id=42)

        # Assert
        client.get_document.assert_called_once_with(42)
        assert result == {10, 20}

    def test_falls_back_to_fallback_doc_on_exception(self):
        # Arrange
        client = MagicMock()
        client.get_document.side_effect = ConnectionError("network down")
        fallback = {"tags": [99, 100]}

        # Act
        result = get_latest_tags(client, doc_id=42, fallback_doc=fallback)

        # Assert
        assert result == {99, 100}

    def test_returns_empty_set_when_exception_and_no_fallback(self):
        # Arrange
        client = MagicMock()
        client.get_document.side_effect = ConnectionError("network down")

        # Act
        result = get_latest_tags(client, doc_id=42)

        # Assert
        assert result == set()

    def test_returns_empty_set_when_exception_and_fallback_is_none(self):
        # Arrange
        client = MagicMock()
        client.get_document.side_effect = OSError("fail")

        # Act
        result = get_latest_tags(client, doc_id=42, fallback_doc=None)

        # Assert
        assert result == set()


# ---------------------------------------------------------------------------
# remove_stale_queue_tag
# ---------------------------------------------------------------------------

class TestRemoveStaleQueueTag:
    """Tests for remove_stale_queue_tag()."""

    def test_removes_pre_tag_id_from_tags_and_updates(self):
        # Arrange
        client = MagicMock()
        tags = {10, 20, 30}
        pre_tag_id = 10

        # Act
        remove_stale_queue_tag(client, doc_id=1, tags=tags, pre_tag_id=pre_tag_id)

        # Assert
        call_args = client.update_document_metadata.call_args
        assert pre_tag_id not in call_args.kwargs["tags"]

    def test_also_removes_processing_tag_id_when_provided(self):
        # Arrange
        client = MagicMock()
        tags = {10, 20, 30}

        # Act
        remove_stale_queue_tag(
            client, doc_id=1, tags=tags,
            pre_tag_id=10, processing_tag_id=20,
        )

        # Assert
        call_args = client.update_document_metadata.call_args
        updated_tags = set(call_args.kwargs["tags"])
        assert 10 not in updated_tags
        assert 20 not in updated_tags
        assert 30 in updated_tags

    def test_handles_api_error_gracefully(self):
        # Arrange
        client = MagicMock()
        client.update_document_metadata.side_effect = ConnectionError("API error")
        tags = {10, 20}

        # Act — should not raise
        remove_stale_queue_tag(client, doc_id=1, tags=tags, pre_tag_id=10)

        # Assert — the call was attempted
        client.update_document_metadata.assert_called_once()

    def test_does_not_mutate_original_tags_set(self):
        # Arrange
        client = MagicMock()
        original_tags = {10, 20, 30}
        tags_copy = set(original_tags)

        # Act
        remove_stale_queue_tag(client, doc_id=1, tags=original_tags, pre_tag_id=10)

        # Assert — original set unchanged
        assert original_tags == tags_copy


# ---------------------------------------------------------------------------
# release_processing_tag
# ---------------------------------------------------------------------------

class TestReleaseProcessingTag:
    """Tests for release_processing_tag()."""

    def test_does_nothing_when_tag_id_is_none(self):
        # Arrange
        client = MagicMock()

        # Act
        release_processing_tag(client, doc_id=1, tag_id=None, purpose="test")

        # Assert
        client.get_document.assert_not_called()
        client.update_document_metadata.assert_not_called()

    def test_does_nothing_when_tag_id_is_zero(self):
        # Arrange
        client = MagicMock()

        # Act
        release_processing_tag(client, doc_id=1, tag_id=0, purpose="test")

        # Assert
        client.get_document.assert_not_called()
        client.update_document_metadata.assert_not_called()

    def test_removes_tag_when_present_in_document(self):
        # Arrange
        client = MagicMock()
        client.get_document.return_value = {"tags": [50, 60, 70]}
        tag_to_remove = 60

        # Act
        release_processing_tag(client, doc_id=1, tag_id=tag_to_remove, purpose="test")

        # Assert
        call_args = client.update_document_metadata.call_args
        updated_tags = set(call_args.kwargs["tags"])
        assert tag_to_remove not in updated_tags
        assert 50 in updated_tags
        assert 70 in updated_tags

    def test_does_nothing_when_tag_not_present_in_document(self):
        # Arrange
        client = MagicMock()
        client.get_document.return_value = {"tags": [50, 70]}

        # Act
        release_processing_tag(client, doc_id=1, tag_id=999, purpose="test")

        # Assert
        client.update_document_metadata.assert_not_called()

    def test_handles_refresh_exception_gracefully(self):
        # Arrange
        client = MagicMock()
        client.get_document.side_effect = ConnectionError("fail")

        # Act — should not raise
        release_processing_tag(client, doc_id=1, tag_id=50, purpose="test")

        # Assert
        client.update_document_metadata.assert_not_called()

    def test_handles_update_exception_gracefully(self):
        # Arrange
        client = MagicMock()
        client.get_document.return_value = {"tags": [50, 60]}
        client.update_document_metadata.side_effect = ConnectionError("patch fail")

        # Act — should not raise
        release_processing_tag(client, doc_id=1, tag_id=50, purpose="test")

        # Assert
        client.update_document_metadata.assert_called_once()


# ---------------------------------------------------------------------------
# clean_pipeline_tags
# ---------------------------------------------------------------------------

class TestCleanPipelineTags:
    """Tests for clean_pipeline_tags()."""

    def test_removes_pre_post_and_classify_pre_tag_ids(self):
        # Arrange
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=None, CLASSIFY_PROCESSING_TAG_ID=None,
            CLASSIFY_POST_TAG_ID=None, ERROR_TAG_ID=None,
        )
        tags = {1, 2, 3, 100, 200}

        # Act
        result = clean_pipeline_tags(tags, settings)

        # Assert
        assert result == {100, 200}

    def test_removes_optional_tags_when_configured(self):
        # Arrange
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=10, CLASSIFY_PROCESSING_TAG_ID=11,
            CLASSIFY_POST_TAG_ID=12, ERROR_TAG_ID=13,
        )
        tags = {1, 2, 3, 10, 11, 12, 13, 500}

        # Act
        result = clean_pipeline_tags(tags, settings)

        # Assert
        assert result == {500}

    def test_skips_optional_tags_when_none(self):
        # Arrange
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=None, CLASSIFY_PROCESSING_TAG_ID=None,
            CLASSIFY_POST_TAG_ID=None, ERROR_TAG_ID=None,
        )
        tags = {1, 2, 3, 42}

        # Act
        result = clean_pipeline_tags(tags, settings)

        # Assert
        assert result == {42}

    def test_preserves_user_assigned_tags(self):
        # Arrange
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=None, CLASSIFY_PROCESSING_TAG_ID=None,
            CLASSIFY_POST_TAG_ID=None, ERROR_TAG_ID=None,
        )
        user_tags = {800, 900, 1000}
        tags = {1, 2, 3} | user_tags

        # Act
        result = clean_pipeline_tags(tags, settings)

        # Assert
        assert result == user_tags

    def test_returns_new_set_does_not_mutate_original(self):
        # Arrange
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=None, CLASSIFY_PROCESSING_TAG_ID=None,
            CLASSIFY_POST_TAG_ID=None, ERROR_TAG_ID=None,
        )
        original = {1, 2, 3, 42}
        original_copy = set(original)

        # Act
        result = clean_pipeline_tags(original, settings)

        # Assert
        assert original == original_copy
        assert result is not original

    def test_skips_optional_tags_when_zero(self):
        # Arrange — 0 is falsy, same as None for the `if optional_tag:` check
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=0, CLASSIFY_PROCESSING_TAG_ID=0,
            CLASSIFY_POST_TAG_ID=0, ERROR_TAG_ID=0,
        )
        tags = {1, 2, 3, 42}

        # Act
        result = clean_pipeline_tags(tags, settings)

        # Assert
        assert result == {42}
