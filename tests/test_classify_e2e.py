"""End-to-end tests for the ClassificationProcessor.process() workflow.

These tests exercise the full process() method with mocked dependencies,
verifying the critical invariant: the processing-lock tag is always released
in the finally block, regardless of how classification fails.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from common.config import Settings
from classifier.result import ClassificationResult
from classifier.worker import ClassificationProcessor


@pytest.fixture
def settings(mocker):
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "PRE_TAG_ID": "10",
            "POST_TAG_ID": "11",
            "ERROR_TAG_ID": "99",
            "CLASSIFY_PRE_TAG_ID": "11",
            "CLASSIFY_POST_TAG_ID": "12",
            "CLASSIFY_PROCESSING_TAG_ID": "60",
            "CLASSIFY_TAG_LIMIT": "5",
            "CLASSIFY_MAX_PAGES": "3",
            "CLASSIFY_TAIL_PAGES": "1",
        },
        clear=True,
    )
    return Settings()


def _make_result(**overrides):
    """Create a ClassificationResult with defaults."""
    defaults = {
        "title": "Test Invoice",
        "correspondent": "Acme Corp",
        "document_type": "Invoice",
        "tags": ["finance", "2025"],
        "document_date": "2025-01-15",
        "language": "en",
        "person": None,
    }
    defaults.update(overrides)
    return ClassificationResult(**defaults)


def _make_processor(settings, content="Page 1\nOCR text here", doc=None, result=None):
    """Build a ClassificationProcessor with mocked dependencies."""
    doc = doc or {"id": 1, "title": "Test Doc", "tags": [11], "content": content, "created": "2025-01-01"}
    client = MagicMock()
    client.get_document.return_value = dict(doc)

    classifier = MagicMock()
    result = result or _make_result()
    classifier.classify_text.return_value = (result, "gpt-5-mini")
    classifier.get_stats.return_value = {}

    taxonomy_cache = MagicMock()
    taxonomy_cache.correspondent_names.return_value = ["Acme Corp"]
    taxonomy_cache.document_type_names.return_value = ["Invoice"]
    taxonomy_cache.tag_names.return_value = ["finance"]
    taxonomy_cache.get_or_create_tag_ids.return_value = [100, 101]
    taxonomy_cache.get_or_create_correspondent_id.return_value = 5
    taxonomy_cache.get_or_create_document_type_id.return_value = 3

    processor = ClassificationProcessor(doc, client, classifier, taxonomy_cache, settings)
    return processor, client, classifier


def test_happy_path_classifies_and_applies_metadata(settings):
    """Full success: claim -> classify -> apply metadata -> release lock."""
    processor, client, classifier = _make_processor(settings)

    with patch("classifier.worker.claim_processing_tag", return_value=True), \
         patch("classifier.worker.release_processing_tag") as mock_release:
        processor.process()

    # Metadata was applied
    client.update_document_metadata.assert_called()
    # Find the metadata update call (not the lock release call)
    metadata_calls = [
        c for c in client.update_document_metadata.call_args_list
        if c.kwargs.get("title") is not None
    ]
    assert len(metadata_calls) == 1
    call_kwargs = metadata_calls[0].kwargs
    assert call_kwargs["title"] == "Test Invoice"
    assert call_kwargs["correspondent_id"] == 5
    assert call_kwargs["document_type_id"] == 3

    mock_release.assert_called_once()


def test_claim_fails_returns_early(settings):
    """If claim_processing_tag returns False, process() returns immediately."""
    processor, client, classifier = _make_processor(settings)

    with patch("classifier.worker.claim_processing_tag", return_value=False):
        processor.process()

    classifier.classify_text.assert_not_called()


def test_error_tag_already_present_skips(settings):
    """Documents with error tag are finalized and skipped."""
    doc = {"id": 1, "title": "Errored", "tags": [11, 99], "content": "text"}
    processor, client, classifier = _make_processor(settings, doc=doc)
    client.get_document.return_value = dict(doc)

    processor.process()

    classifier.classify_text.assert_not_called()


def test_empty_content_requeues(settings):
    """Documents with empty content are requeued for OCR."""
    processor, client, classifier = _make_processor(settings, content="   ")

    with patch("classifier.worker.claim_processing_tag", return_value=True), \
         patch("classifier.worker.release_processing_tag") as mock_release:
        processor.process()

    classifier.classify_text.assert_not_called()
    # Document was requeued — update_document_metadata was called
    client.update_document_metadata.assert_called()
    mock_release.assert_called_once()


def test_empty_result_marks_error(settings):
    """When LLM returns empty classification, document gets error tag."""
    result = _make_result(title="", correspondent="", document_type="", tags=[])
    processor, client, classifier = _make_processor(settings, result=result)
    classifier.classify_text.return_value = (result, "gpt-5-mini")

    with patch("classifier.worker.claim_processing_tag", return_value=True), \
         patch("classifier.worker.release_processing_tag") as mock_release, \
         patch("classifier.worker.is_empty_classification", return_value=True):
        processor.process()

    # Error path taken
    client.update_document_metadata.assert_called()
    mock_release.assert_called_once()


def test_generic_document_type_marks_error(settings):
    """When LLM returns a generic document type, document gets error tag."""
    result = _make_result(document_type="Document")
    processor, client, classifier = _make_processor(settings, result=result)
    classifier.classify_text.return_value = (result, "gpt-5-mini")

    with patch("classifier.worker.claim_processing_tag", return_value=True), \
         patch("classifier.worker.release_processing_tag") as mock_release, \
         patch("classifier.worker.is_generic_document_type", return_value=True):
        processor.process()

    # Error finalization happened
    client.update_document_metadata.assert_called()
    mock_release.assert_called_once()


def test_llm_failure_releases_lock(settings):
    """When the LLM call raises, the processing-lock is still released."""
    processor, client, classifier = _make_processor(settings)
    classifier.classify_text.side_effect = RuntimeError("LLM unavailable")

    with patch("classifier.worker.claim_processing_tag", return_value=True), \
         patch("classifier.worker.release_processing_tag") as mock_release:
        with pytest.raises(RuntimeError, match="LLM unavailable"):
            processor.process()

    # Lock was released via finally
    mock_release.assert_called_once()
