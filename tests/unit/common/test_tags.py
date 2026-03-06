"""Tests for common.tags."""

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

class TestExtractTags:
    """Tests for extract_tags()."""

    def test_returns_set_of_ints_from_doc_tags(self):
        doc = {"tags": [1, 2, 3]}

        result = extract_tags(doc, doc_id=1, context="test")

        assert result == {1, 2, 3}

    def test_returns_empty_set_when_tags_key_missing(self):
        doc = {"id": 1, "title": "No tags key"}

        result = extract_tags(doc, doc_id=1, context="test")

        assert result == set()

    def test_returns_empty_set_when_tags_is_none(self):
        doc = {"tags": None}

        result = extract_tags(doc, doc_id=1, context="test")

        assert result == set()

    def test_returns_empty_set_when_tags_is_not_a_list(self):
        doc = {"tags": "not-a-list"}

        result = extract_tags(doc, doc_id=1, context="test")

        assert result == set()

    def test_handles_empty_list(self):
        doc = {"tags": []}

        result = extract_tags(doc, doc_id=1, context="test")

        assert result == set()

    def test_returns_set_preserving_unique_ids(self):
        doc = {"tags": [5, 5, 10]}

        result = extract_tags(doc, doc_id=1, context="test")

        assert result == {5, 10}

class TestGetLatestTags:
    """Tests for get_latest_tags()."""

    def test_fetches_fresh_document_and_extracts_tags(self):
        client = MagicMock()
        client.get_document.return_value = {"tags": [10, 20]}

        result = get_latest_tags(client, doc_id=42)

        client.get_document.assert_called_once_with(42)
        assert result == {10, 20}

    def test_falls_back_to_fallback_doc_on_exception(self):
        client = MagicMock()
        client.get_document.side_effect = ConnectionError("network down")
        fallback = {"tags": [99, 100]}

        result = get_latest_tags(client, doc_id=42, fallback_doc=fallback)

        assert result == {99, 100}

    def test_returns_empty_set_when_exception_and_no_fallback(self):
        client = MagicMock()
        client.get_document.side_effect = ConnectionError("network down")

        result = get_latest_tags(client, doc_id=42)

        assert result == set()

    def test_returns_empty_set_when_exception_and_fallback_is_none(self):
        client = MagicMock()
        client.get_document.side_effect = OSError("fail")

        result = get_latest_tags(client, doc_id=42, fallback_doc=None)

        assert result == set()

class TestRemoveStaleQueueTag:
    """Tests for remove_stale_queue_tag()."""

    def test_removes_pre_tag_id_from_tags_and_updates(self):
        client = MagicMock()
        tags = {10, 20, 30}
        pre_tag_id = 10

        remove_stale_queue_tag(client, doc_id=1, tags=tags, pre_tag_id=pre_tag_id)

        call_args = client.update_document_metadata.call_args
        assert pre_tag_id not in call_args.kwargs["tags"]

    def test_also_removes_processing_tag_id_when_provided(self):
        client = MagicMock()
        tags = {10, 20, 30}

        remove_stale_queue_tag(
            client, doc_id=1, tags=tags,
            pre_tag_id=10, processing_tag_id=20,
        )

        call_args = client.update_document_metadata.call_args
        updated_tags = set(call_args.kwargs["tags"])
        assert 10 not in updated_tags
        assert 20 not in updated_tags
        assert 30 in updated_tags

    def test_handles_api_error_gracefully(self):
        client = MagicMock()
        client.update_document_metadata.side_effect = ConnectionError("API error")
        tags = {10, 20}

        remove_stale_queue_tag(client, doc_id=1, tags=tags, pre_tag_id=10)

        client.update_document_metadata.assert_called_once()

    def test_does_not_mutate_original_tags_set(self):
        client = MagicMock()
        original_tags = {10, 20, 30}
        tags_copy = set(original_tags)

        remove_stale_queue_tag(client, doc_id=1, tags=original_tags, pre_tag_id=10)

        assert original_tags == tags_copy

class TestReleaseProcessingTag:
    """Tests for release_processing_tag()."""

    def test_does_nothing_when_tag_id_is_none(self):
        client = MagicMock()

        release_processing_tag(client, doc_id=1, tag_id=None, purpose="test")

        client.get_document.assert_not_called()
        client.update_document_metadata.assert_not_called()

    def test_removes_tag_when_present_in_document(self):
        client = MagicMock()
        client.get_document.return_value = {"tags": [50, 60, 70]}
        tag_to_remove = 60

        release_processing_tag(client, doc_id=1, tag_id=tag_to_remove, purpose="test")

        call_args = client.update_document_metadata.call_args
        updated_tags = set(call_args.kwargs["tags"])
        assert tag_to_remove not in updated_tags
        assert 50 in updated_tags
        assert 70 in updated_tags

    def test_does_nothing_when_tag_not_present_in_document(self):
        client = MagicMock()
        client.get_document.return_value = {"tags": [50, 70]}

        release_processing_tag(client, doc_id=1, tag_id=999, purpose="test")

        client.update_document_metadata.assert_not_called()

    def test_handles_refresh_exception_gracefully(self):
        client = MagicMock()
        client.get_document.side_effect = ConnectionError("fail")

        release_processing_tag(client, doc_id=1, tag_id=50, purpose="test")

        client.update_document_metadata.assert_not_called()

    def test_handles_update_exception_gracefully(self):
        client = MagicMock()
        client.get_document.return_value = {"tags": [50, 60]}
        client.update_document_metadata.side_effect = ConnectionError("patch fail")

        release_processing_tag(client, doc_id=1, tag_id=50, purpose="test")

        client.update_document_metadata.assert_called_once()

class TestCleanPipelineTags:
    """Tests for clean_pipeline_tags()."""

    def test_removes_pre_post_and_classify_pre_tag_ids(self):
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=None, CLASSIFY_PROCESSING_TAG_ID=None,
            CLASSIFY_POST_TAG_ID=None, ERROR_TAG_ID=None,
        )
        tags = {1, 2, 3, 100, 200}

        result = clean_pipeline_tags(tags, settings)

        assert result == {100, 200}

    def test_removes_optional_tags_when_configured(self):
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=10, CLASSIFY_PROCESSING_TAG_ID=11,
            CLASSIFY_POST_TAG_ID=12, ERROR_TAG_ID=13,
        )
        tags = {1, 2, 3, 10, 11, 12, 13, 500}

        result = clean_pipeline_tags(tags, settings)

        assert result == {500}

    def test_skips_optional_tags_when_none(self):
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=None, CLASSIFY_PROCESSING_TAG_ID=None,
            CLASSIFY_POST_TAG_ID=None, ERROR_TAG_ID=None,
        )
        tags = {1, 2, 3, 42}

        result = clean_pipeline_tags(tags, settings)

        assert result == {42}

    def test_preserves_user_assigned_tags(self):
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=None, CLASSIFY_PROCESSING_TAG_ID=None,
            CLASSIFY_POST_TAG_ID=None, ERROR_TAG_ID=None,
        )
        user_tags = {800, 900, 1000}
        tags = {1, 2, 3} | user_tags

        result = clean_pipeline_tags(tags, settings)

        assert result == user_tags

    def test_returns_new_set_does_not_mutate_original(self):
        settings = make_settings_obj(
            PRE_TAG_ID=1, POST_TAG_ID=2, CLASSIFY_PRE_TAG_ID=3,
            OCR_PROCESSING_TAG_ID=None, CLASSIFY_PROCESSING_TAG_ID=None,
            CLASSIFY_POST_TAG_ID=None, ERROR_TAG_ID=None,
        )
        original = {1, 2, 3, 42}
        original_copy = set(original)

        result = clean_pipeline_tags(original, settings)

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

        result = clean_pipeline_tags(tags, settings)

        assert result == {42}
