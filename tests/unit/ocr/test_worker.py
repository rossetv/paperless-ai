"""Tests for ocr.worker — the end-to-end ``OcrProcessor.process()`` lifecycle.

The per-method helpers (page OCR, the Paperless update, error finalisation,
stats) are covered in ``test_worker_internals``; this file is split off it for
the 500-line ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from ocr.image_converter import ImageConversionError
from ocr.text_assembly import PageResult
from ocr.worker import OcrProcessor
from tests.helpers.factories import make_document, make_settings_obj
from tests.helpers.mocks import make_mock_ocr_provider, make_mock_paperless
from tests.unit.ocr.conftest import make_image, make_processor


class TestProcessHappyPath:
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.bytes_to_images")
    @patch("ocr.worker.assemble_full_text")
    def test_full_pipeline_success(
        self, mock_assemble, mock_b2i, mock_claim, mock_release
    ):
        settings = make_settings_obj(
            OCR_PROCESSING_TAG_ID=999,
            ERROR_TAG_ID=552,
        )
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "Test", "tags": [443]}
        paperless.download_content.return_value = (b"pdf-data", "application/pdf")

        images = [make_image(), make_image()]
        mock_b2i.return_value = images

        ocr_provider = make_mock_ocr_provider()
        ocr_provider.transcribe_image.side_effect = [
            PageResult("Page 1 text", "model-a"),
            PageResult("Page 2 text", "model-a"),
        ]

        mock_assemble.return_value = (
            "Full text\n\nTranscribed by model: model-a",
            {"model-a"},
        )

        proc = OcrProcessor(
            {"id": 1, "title": "Test", "tags": [443]},
            paperless,
            ocr_provider,
            settings,
        )

        proc.process()

        # Assert — full pipeline invoked with correct data flow
        mock_claim.assert_called_once()
        paperless.download_content.assert_called_once_with(1)
        mock_b2i.assert_called_once()
        mock_assemble.assert_called_once()
        mock_release.assert_called_once()
        # Verify update_document called with correct content and tags
        paperless.update_document.assert_called_once()
        call_args = paperless.update_document.call_args[0]
        assert call_args[0] == 1  # doc_id
        assert "Full text" in call_args[1]  # OCR text
        tags = call_args[2]
        assert 444 in tags  # POST_TAG_ID added
        assert 443 not in tags  # PRE_TAG_ID removed


class TestProcessClaimFails:
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=False)
    def test_claim_fails_returns_early(self, mock_claim, mock_release):
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        proc = make_processor(paperless=paperless)

        proc.process()

        paperless.download_content.assert_not_called()
        # Release not called because claimed=False
        mock_release.assert_not_called()


class TestProcessErrorTagPresent:
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag")
    @patch("common.tags.clean_pipeline_tags")
    def test_error_tag_skips_ocr(self, mock_clean, mock_claim, mock_release):
        settings = make_settings_obj(ERROR_TAG_ID=552)
        paperless = make_mock_paperless()
        # Return doc with error tag
        paperless.get_document.return_value = {
            "id": 1,
            "title": "T",
            "tags": [443, 552],
        }
        mock_clean.return_value = {552}

        proc = make_processor(paperless=paperless, settings=settings)

        proc.process()

        # Assert — claim never called, finalise_with_error called via clean_pipeline_tags
        mock_claim.assert_not_called()
        paperless.download_content.assert_not_called()
        mock_clean.assert_called_once()
        paperless.update_document_metadata.assert_called_once()


class TestProcessRefreshFailure:
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag")
    def test_refresh_failure_propagates(self, mock_claim, mock_release):
        paperless = make_mock_paperless()
        paperless.get_document.side_effect = ConnectionError("Network error")
        proc = make_processor(paperless=paperless)

        # Act — exception propagates to the caller (daemon thread pool handles it)
        with pytest.raises(ConnectionError, match="Network error"):
            proc.process()

        mock_claim.assert_not_called()
        paperless.download_content.assert_not_called()
        mock_release.assert_not_called()


class TestProcessImageConversionFailure:
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch(
        "ocr.worker.bytes_to_images",
        side_effect=ImageConversionError("Bad image"),
    )
    @patch("common.tags.clean_pipeline_tags")
    def test_conversion_failure_finalises_error(
        self, mock_clean, mock_b2i, mock_claim, mock_release
    ):
        settings = make_settings_obj(
            OCR_PROCESSING_TAG_ID=999,
            ERROR_TAG_ID=552,
        )
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        mock_clean.return_value = {552}

        proc = make_processor(paperless=paperless, settings=settings)

        proc.process()

        mock_release.assert_called_once()


class TestProcessAlwaysReleasesLock:
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.bytes_to_images")
    def test_lock_released_on_download_failure(
        self, mock_b2i, mock_claim, mock_release
    ):
        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=999)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        paperless.download_content.side_effect = Exception("Download failed")

        proc = make_processor(paperless=paperless, settings=settings)

        with pytest.raises(Exception, match="Download failed"):
            proc.process()

        mock_release.assert_called_once()

    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.bytes_to_images")
    def test_lock_released_on_ocr_failure(self, mock_b2i, mock_claim, mock_release):
        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=999)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        images = [make_image()]
        mock_b2i.return_value = images

        ocr_provider = make_mock_ocr_provider()
        ocr_provider.transcribe_image.side_effect = Exception("OCR boom")

        proc = make_processor(
            paperless=paperless, ocr_provider=ocr_provider, settings=settings
        )

        # Act — the per-page failure is isolated inside the thread pool, so
        # process() does not raise; the page result carries the error marker.
        proc.process()

        mock_release.assert_called_once()


class TestImagesAlwaysClosed:
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.bytes_to_images")
    @patch("ocr.worker.assemble_full_text", return_value=("text", {"m"}))
    @patch("ocr.worker.get_latest_tags", return_value={443})
    def test_images_closed_on_success(
        self, mock_tags, mock_assemble, mock_b2i, mock_claim, mock_release
    ):
        img1 = MagicMock(spec=Image.Image)
        img2 = MagicMock(spec=Image.Image)
        mock_b2i.return_value = [img1, img2]

        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=None)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        ocr_provider = make_mock_ocr_provider()

        proc = make_processor(
            paperless=paperless, ocr_provider=ocr_provider, settings=settings
        )

        proc.process()

        img1.close.assert_called_once()
        img2.close.assert_called_once()

    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.bytes_to_images")
    def test_images_closed_on_ocr_error(self, mock_b2i, mock_claim, mock_release):
        img1 = MagicMock(spec=Image.Image)
        mock_b2i.return_value = [img1]

        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=999)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}

        ocr_provider = make_mock_ocr_provider()
        ocr_provider.transcribe_image.side_effect = Exception("OCR boom")

        proc = make_processor(
            paperless=paperless, ocr_provider=ocr_provider, settings=settings
        )

        proc.process()

        img1.close.assert_called_once()


class TestOcrProcessorInit:
    def test_extracts_doc_id(self):
        doc = make_document(id=42)

        proc = make_processor(doc=doc)

        assert proc.doc_id == 42

    def test_title_defaults_to_untitled(self):
        doc = make_document(title=None)

        proc = make_processor(doc=doc)

        assert proc.title == "<untitled>"

    def test_title_from_doc(self):
        doc = make_document(title="My Document")

        proc = make_processor(doc=doc)

        assert proc.title == "My Document"


class TestProcessNoPages:
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.bytes_to_images", return_value=[])
    def test_no_pages_returns_early(self, mock_b2i, mock_claim, mock_release):
        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=999)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        ocr_provider = make_mock_ocr_provider()

        proc = make_processor(
            paperless=paperless, ocr_provider=ocr_provider, settings=settings
        )

        proc.process()

        ocr_provider.transcribe_image.assert_not_called()
        # Lock still released
        mock_release.assert_called_once()
