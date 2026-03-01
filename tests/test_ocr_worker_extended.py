"""Extended tests for ocr.worker — error paths and edge cases."""

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
            "OCR_PROCESSING_TAG_ID": "99",
            "ERROR_TAG_ID": "552",
        },
        clear=True,
    )
    return Settings()


@pytest.fixture
def mock_doc():
    return {"id": 1, "title": "Test", "tags": [10]}


def test_process_skips_when_error_tag_present(settings, mock_doc):
    paperless = MagicMock()
    doc_with_error = {"id": 1, "tags": [10, 552], "title": "Test"}
    paperless.get_document.side_effect = [
        dict(doc_with_error),  # process refresh — error tag present
        dict(doc_with_error),  # any further calls
    ]
    ocr_provider = MagicMock()

    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)
    processor.process()

    ocr_provider.transcribe_image.assert_not_called()
    paperless.download_content.assert_not_called()
    # Should have marked error (removed pipeline tags, added error tag)
    paperless.update_document_metadata.assert_called()


def test_process_handles_refresh_failure(settings, mock_doc):
    paperless = MagicMock()
    paperless.get_document.side_effect = ConnectionError("network down")
    ocr_provider = MagicMock()

    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)
    processor.process()

    # Should return early without processing
    paperless.download_content.assert_not_called()
    ocr_provider.transcribe_image.assert_not_called()


@patch("ocr.image_converter.convert_from_bytes")
def test_process_handles_corrupted_image(mock_convert, settings, mock_doc):
    """_bytes_to_images raising RuntimeError should mark error instead of infinite retry."""
    paperless = MagicMock()
    processing_tag = settings.OCR_PROCESSING_TAG_ID
    base_doc = {"id": 1, "tags": [10], "title": "Test"}
    claimed_doc = {"id": 1, "tags": [10, processing_tag], "title": "Test"}
    paperless.get_document.side_effect = [
        dict(base_doc),    # process refresh
        dict(base_doc),    # claim refresh
        dict(claimed_doc), # claim verify
        dict(claimed_doc), # _finalize_with_error get_document
        dict(claimed_doc), # release_processing_tag get_document
        dict(claimed_doc), # extra safety
    ]
    paperless.download_content.return_value = (b"bad data", "image/png")
    ocr_provider = MagicMock()

    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    with patch.object(processor, '_bytes_to_images', side_effect=RuntimeError("bad")):
        processor.process()

    # Should mark error, not propagate the exception
    calls = paperless.update_document_metadata.call_args_list
    # Find the error marking call (should have ERROR_TAG_ID in tags)
    error_calls = [c for c in calls if settings.ERROR_TAG_ID in c[1].get("tags", [])]
    assert len(error_calls) >= 1


def test_assemble_full_text_single_page_no_header(settings, mock_doc):
    paperless = MagicMock()
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    page_results = [("Single page text", "model-a")]
    full_text, models = processor._assemble_full_text(1, page_results)

    assert "--- Page" not in full_text
    assert "Single page text" in full_text
    assert "Transcribed by model: model-a" in full_text
    assert models == {"model-a"}


def test_assemble_full_text_empty_produces_empty(settings, mock_doc):
    paperless = MagicMock()
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    page_results = [("", "")]
    full_text, models = processor._assemble_full_text(1, page_results)

    assert full_text == ""
    assert models == set()


def test_update_document_marks_error_on_redacted_content(settings, mock_doc):
    paperless = MagicMock()
    paperless.get_document.return_value = {"id": 1, "tags": [10]}
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    processor._update_paperless_document("[REDACTED NAME] text", {"model-a"})

    args, _ = paperless.update_document.call_args
    assert settings.ERROR_TAG_ID in set(args[2])


def test_update_document_marks_error_on_ocr_error_marker(settings, mock_doc):
    paperless = MagicMock()
    paperless.get_document.return_value = {"id": 1, "tags": [10]}
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    processor._update_paperless_document(
        "[OCR ERROR] Failed to OCR page 1.", {"model-a"}
    )

    args, _ = paperless.update_document.call_args
    assert settings.ERROR_TAG_ID in set(args[2])


def test_finalize_with_error_no_error_tag_configured(settings, mock_doc):
    settings.ERROR_TAG_ID = None
    paperless = MagicMock()
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    processor._finalize_with_error({10, 42})

    call_kwargs = paperless.update_document_metadata.call_args[1]
    assert 10 not in call_kwargs["tags"]  # pipeline tag removed
    assert 42 in call_kwargs["tags"]       # user tag kept


def test_finalize_with_error_includes_content(settings, mock_doc):
    paperless = MagicMock()
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    processor._finalize_with_error({10, 42}, content="some error text")

    # When content is provided, update_document is used instead of update_document_metadata
    paperless.update_document.assert_called_once()
    args, _ = paperless.update_document.call_args
    assert args[1] == "some error text"


def test_log_ocr_stats_no_stats_method(settings, mock_doc):
    """Provider without get_stats should not crash."""
    paperless = MagicMock()
    ocr_provider = MagicMock(spec=[])  # No get_stats attribute
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)
    # Should not raise
    processor._log_ocr_stats()


def test_log_ocr_stats_empty_stats(settings, mock_doc):
    """Provider returning empty stats should not crash."""
    paperless = MagicMock()
    ocr_provider = MagicMock()
    ocr_provider.get_stats.return_value = {"attempts": 0}
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)
    # Should not raise
    processor._log_ocr_stats()


def test_process_returns_when_claim_fails(settings, mock_doc):
    """Line 86: When processing tag claim fails, process returns early."""
    paperless = MagicMock()
    base_doc = {"id": 1, "tags": [10], "title": "Test"}
    # Claim will see processing tag already present → claim fails
    claimed_doc = {"id": 1, "tags": [10, 99], "title": "Test"}
    paperless.get_document.side_effect = [
        dict(base_doc),     # process refresh
        dict(claimed_doc),  # claim refresh — tag already present
    ]
    ocr_provider = MagicMock()

    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)
    processor.process()

    paperless.download_content.assert_not_called()
    ocr_provider.transcribe_image.assert_not_called()


def test_process_image_close_failure_logged(settings, mock_doc):
    """Lines 109-110: image.close() failure is logged but doesn't crash."""
    paperless = MagicMock()
    processing_tag = settings.OCR_PROCESSING_TAG_ID
    base_doc = {"id": 1, "tags": [10], "title": "Test"}
    claimed_doc = {"id": 1, "tags": [10, processing_tag], "title": "Test"}
    paperless.get_document.side_effect = [
        dict(base_doc),      # process refresh
        dict(base_doc),      # claim refresh
        dict(claimed_doc),   # claim verify
        dict(claimed_doc),   # _update_paperless_document get_document
        dict(claimed_doc),   # release
        dict(claimed_doc),   # extra
    ]
    paperless.download_content.return_value = (b"dummy", "image/png")

    img = MagicMock()
    img.close.side_effect = OSError("cannot close")
    ocr_provider = MagicMock()
    ocr_provider.transcribe_image.return_value = ("text", "model-a")

    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    with patch.object(processor, '_bytes_to_images', return_value=[img]):
        processor.process()

    img.close.assert_called_once()
    paperless.update_document.assert_called_once()


def test_update_document_discards_processing_tag(settings, mock_doc):
    """Line 269: OCR_PROCESSING_TAG_ID is removed from final tags."""
    paperless = MagicMock()
    processing_tag = settings.OCR_PROCESSING_TAG_ID
    paperless.get_document.return_value = {"id": 1, "tags": [10, processing_tag, 42]}
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    processor._update_paperless_document("good text", {"model-a"})

    args, _ = paperless.update_document.call_args
    tag_set = set(args[2])
    assert processing_tag not in tag_set
    assert settings.PRE_TAG_ID not in tag_set
    assert settings.POST_TAG_ID in tag_set
    assert 42 in tag_set
