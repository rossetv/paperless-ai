"""End-to-end tests for the OCR DocumentProcessor.process() workflow.

These tests exercise the full process() method with mocked dependencies,
verifying the critical invariant: the processing-lock tag is always released
in the finally block, regardless of how processing fails.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from common.config import Settings
from ocr.worker import DocumentProcessor


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
            "OCR_PROCESSING_TAG_ID": "50",
            "PAGE_WORKERS": "1",
        },
        clear=True,
    )
    return Settings()


def _make_processor(settings, doc=None, ocr_text="Hello World", ocr_model="gpt-5-mini"):
    """Build a DocumentProcessor with mocked dependencies."""
    doc = doc or {"id": 1, "title": "Test Doc", "tags": [10]}
    client = MagicMock()
    client.get_document.return_value = dict(doc)
    client.download_content.return_value = (b"fake-pdf-bytes", "application/pdf")

    provider = MagicMock()
    provider.transcribe_image.return_value = (ocr_text, ocr_model)
    provider.get_stats.return_value = {}

    processor = DocumentProcessor(doc, client, provider, settings)
    return processor, client, provider


def test_happy_path_claims_ocrs_updates_and_releases(settings):
    """Full success: claim -> OCR -> update Paperless -> release lock."""
    processor, client, provider = _make_processor(settings)

    with patch("ocr.worker.bytes_to_images") as mock_convert, \
         patch("ocr.worker.claim_processing_tag", return_value=True), \
         patch("ocr.worker.release_processing_tag") as mock_release:
        img = MagicMock(spec=Image.Image)
        mock_convert.return_value = [img]
        processor.process()

    # Document was updated with OCR text and post-tag
    client.update_document.assert_called_once()
    call_args = client.update_document.call_args
    assert call_args[0][0] == 1  # doc_id
    assert "Hello World" in call_args[0][1]  # OCR text
    assert 11 in call_args[0][2]  # post tag
    assert 10 not in call_args[0][2]  # pre tag removed

    # Lock was released
    mock_release.assert_called_once()


def test_claim_fails_no_processing(settings):
    """If claim_processing_tag returns False, process() returns early."""
    processor, client, provider = _make_processor(settings)

    with patch("ocr.worker.claim_processing_tag", return_value=False):
        processor.process()

    client.download_content.assert_not_called()
    provider.transcribe_image.assert_not_called()


def test_error_tag_already_present_skips(settings):
    """Documents with error tag are finalized and skipped."""
    doc = {"id": 1, "title": "Errored Doc", "tags": [10, 99]}
    processor, client, provider = _make_processor(settings, doc=doc)
    client.get_document.return_value = dict(doc)

    processor.process()

    provider.transcribe_image.assert_not_called()
    client.download_content.assert_not_called()


def test_ocr_failure_releases_lock(settings):
    """When OCR fails for all pages, the processing-lock tag is still released."""
    processor, client, provider = _make_processor(settings)
    provider.transcribe_image.side_effect = RuntimeError("LLM down")

    with patch("ocr.worker.bytes_to_images") as mock_convert, \
         patch("ocr.worker.claim_processing_tag", return_value=True), \
         patch("ocr.worker.release_processing_tag") as mock_release:
        img = MagicMock(spec=Image.Image)
        mock_convert.return_value = [img]
        processor.process()

    # Lock released despite OCR failure
    mock_release.assert_called_once()


def test_download_failure_releases_lock(settings):
    """When download fails, the processing-lock is still released."""
    processor, client, provider = _make_processor(settings)
    client.download_content.side_effect = RuntimeError("network error")

    with patch("ocr.worker.claim_processing_tag", return_value=True), \
         patch("ocr.worker.release_processing_tag") as mock_release:
        with pytest.raises(RuntimeError):
            processor.process()

    # Lock was released in the finally block
    mock_release.assert_called_once()


def test_image_conversion_failure_marks_error(settings):
    """When bytes_to_images raises, the document gets an error tag."""
    processor, client, provider = _make_processor(settings)

    with patch("ocr.worker.bytes_to_images", side_effect=RuntimeError("bad PDF")), \
         patch("ocr.worker.claim_processing_tag", return_value=True), \
         patch("ocr.worker.release_processing_tag") as mock_release:
        processor.process()

    # Error was marked on the document
    client.update_document_metadata.assert_called()
    mock_release.assert_called_once()


def test_empty_ocr_text_marks_error(settings):
    """When OCR produces empty text, document is marked with error tag."""
    processor, client, provider = _make_processor(settings, ocr_text="   ")

    with patch("ocr.worker.bytes_to_images") as mock_convert, \
         patch("ocr.worker.claim_processing_tag", return_value=True), \
         patch("ocr.worker.release_processing_tag") as mock_release:
        img = MagicMock(spec=Image.Image)
        mock_convert.return_value = [img]
        processor.process()

    # Error path was taken
    client.update_document.assert_called_once()
    mock_release.assert_called_once()
