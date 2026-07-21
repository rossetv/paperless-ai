"""Tests for ocr.worker — the end-to-end ``OcrProcessor.process()`` lifecycle.

The per-method helpers (page OCR, the Paperless update, error finalisation,
stats) are covered in ``test_worker_internals``; this file is split off it for
the 500-line ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from PIL import Image

from common.per_document import WriteBackOutcome
from ocr.born_digital import BornDigitalDecision
from ocr.image_converter import ImageConversionError, PageSource
from ocr.text_assembly import PageResult
from ocr.worker import OcrProcessor
from tests.helpers.factories import make_document, make_settings_obj
from tests.helpers.mocks import make_mock_ocr_provider, make_mock_paperless
from tests.unit.ocr.conftest import (
    _http_status_error,
    make_image,
    make_page_source,
    make_processor,
)


class TestProcessHappyPath:
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.open_page_source")
    @patch("ocr.worker.assemble_full_text")
    def test_full_pipeline_success(
        self, mock_assemble, mock_open_pages, mock_claim, mock_release
    ):
        settings = make_settings_obj(
            OCR_PROCESSING_TAG_ID=999,
            ERROR_TAG_ID=552,
        )
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "Test", "tags": [443]}
        paperless.download_content.return_value = (b"pdf-data", "application/pdf")

        pages = make_page_source([make_image(), make_image()])
        mock_open_pages.return_value = pages

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

        outcome = proc.process()

        # Assert — full pipeline invoked with correct data flow
        assert outcome is WriteBackOutcome.SAVED
        mock_claim.assert_called_once()
        paperless.download_content.assert_called_once_with(1)
        mock_open_pages.assert_called_once()
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
        "ocr.worker.open_page_source",
        side_effect=ImageConversionError("Bad image"),
    )
    @patch("common.tags.clean_pipeline_tags")
    def test_conversion_failure_finalises_error(
        self, mock_clean, mock_open_pages, mock_claim, mock_release
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


class TestProcessWriteBackFailure:
    """A failed OCR write-back must not re-burn vision tokens forever.

    Every page's transcription is already paid for by the time the write-back
    runs, so a permanent (4xx) rejection must quarantine the document — leaving
    it queued would re-OCR it on every poll. A transient (5xx) rejection
    re-raises so the daemon loop retries once Paperless recovers.
    """

    @patch("ocr.worker.get_latest_tags", return_value={443})
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.open_page_source")
    @patch("ocr.worker.assemble_full_text")
    def test_permanent_4xx_quarantines_document(
        self,
        mock_assemble,
        mock_open_pages,
        mock_claim,
        mock_release,
        mock_latest,
    ):
        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=999, ERROR_TAG_ID=552)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        paperless.download_content.return_value = (b"pdf-data", "application/pdf")
        mock_open_pages.return_value = make_page_source([make_image()])
        mock_assemble.return_value = ("Full transcription text", {"model-a"})
        # The happy-path write is rejected 400; the error-tag finalisation
        # (which also uses update_document, with content) then succeeds.
        paperless.update_document.side_effect = [_http_status_error(400), None]

        proc = OcrProcessor(
            {"id": 1, "title": "T", "tags": [443]},
            paperless,
            make_mock_ocr_provider(),
            settings,
        )

        outcome = proc.process()

        assert outcome is WriteBackOutcome.QUARANTINED
        assert paperless.update_document.call_count == 2
        finalise_tags = paperless.update_document.call_args[0][2]
        assert 552 in finalise_tags
        mock_release.assert_called_once()

    @patch("ocr.worker.get_latest_tags", return_value={443})
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.open_page_source")
    @patch("ocr.worker.assemble_full_text")
    def test_transient_5xx_reraises_without_quarantine(
        self,
        mock_assemble,
        mock_open_pages,
        mock_claim,
        mock_release,
        mock_latest,
    ):
        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=999, ERROR_TAG_ID=552)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        paperless.download_content.return_value = (b"pdf-data", "application/pdf")
        mock_open_pages.return_value = make_page_source([make_image()])
        mock_assemble.return_value = ("Full transcription text", {"model-a"})
        paperless.update_document.side_effect = _http_status_error(503)

        proc = OcrProcessor(
            {"id": 1, "title": "T", "tags": [443]},
            paperless,
            make_mock_ocr_provider(),
            settings,
        )

        with pytest.raises(httpx.HTTPStatusError):
            proc.process()

        # Only the happy-path write was attempted — no error-tag finalisation.
        assert paperless.update_document.call_count == 1
        mock_release.assert_called_once()

    @patch("ocr.worker.get_latest_tags", return_value={443})
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.open_page_source")
    @patch("ocr.worker.assemble_full_text")
    def test_bad_ocr_content_is_a_neutral_outcome(
        self,
        mock_assemble,
        mock_open_pages,
        mock_claim,
        mock_release,
        mock_latest,
    ):
        # A document that OCRs to empty/refusal content is error-tagged, but the
        # outcome is None — NOT SAVED. Reporting SAVED here would reset the
        # circuit breaker's failure streak, letting a backlog of blank scans mask
        # a systemic Paperless write failure. This runs the real worker (not a
        # stubbed outcome) so the whole process() path is exercised.
        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=999, ERROR_TAG_ID=552)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        paperless.download_content.return_value = (b"pdf-data", "application/pdf")
        mock_open_pages.return_value = make_page_source([make_image()])
        mock_assemble.return_value = ("   ", {"model-a"})  # empty transcription

        proc = OcrProcessor(
            {"id": 1, "title": "T", "tags": [443]},
            paperless,
            make_mock_ocr_provider(),
            settings,
        )

        outcome = proc.process()

        assert outcome is None
        mock_release.assert_called_once()


class TestProcessAlwaysReleasesLock:
    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.open_page_source")
    def test_lock_released_on_download_failure(
        self, mock_open_pages, mock_claim, mock_release
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
    @patch("ocr.worker.open_page_source")
    def test_lock_released_on_ocr_failure(
        self, mock_open_pages, mock_claim, mock_release
    ):
        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=999)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        mock_open_pages.return_value = make_page_source([make_image()])

        ocr_provider = make_mock_ocr_provider()
        ocr_provider.transcribe_image.side_effect = Exception("OCR boom")

        proc = make_processor(
            paperless=paperless, ocr_provider=ocr_provider, settings=settings
        )

        # Act — the per-page failure is isolated inside the thread pool, so
        # process() does not raise; the page result carries the error marker.
        proc.process()

        mock_release.assert_called_once()


class TestPagesAlwaysReleased:
    """Every page bitmap is released — per-page after OCR and via the source."""

    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.open_page_source")
    @patch("ocr.worker.assemble_full_text", return_value=("text", {"m"}))
    @patch("ocr.worker.get_latest_tags", return_value={443})
    def test_pages_released_on_success(
        self, mock_tags, mock_assemble, mock_open_pages, mock_claim, mock_release
    ):
        img1 = MagicMock(spec=Image.Image)
        img2 = MagicMock(spec=Image.Image)
        mock_open_pages.return_value = make_page_source([img1, img2])

        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=None)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}
        ocr_provider = make_mock_ocr_provider()

        proc = make_processor(
            paperless=paperless, ocr_provider=ocr_provider, settings=settings
        )

        proc.process()

        # Each page is closed after its transcription (and again by the source's
        # close as a backstop) — the binding guarantee is "never leaked".
        assert img1.close.called
        assert img2.close.called

    @patch("ocr.worker.release_processing_tag")
    @patch("ocr.worker.claim_processing_tag", return_value=True)
    @patch("ocr.worker.open_page_source")
    def test_pages_released_on_ocr_error(
        self, mock_open_pages, mock_claim, mock_release
    ):
        img1 = MagicMock(spec=Image.Image)
        mock_open_pages.return_value = make_page_source([img1])

        settings = make_settings_obj(OCR_PROCESSING_TAG_ID=999)
        paperless = make_mock_paperless()
        paperless.get_document.return_value = {"id": 1, "title": "T", "tags": [443]}

        ocr_provider = make_mock_ocr_provider()
        ocr_provider.transcribe_image.side_effect = Exception("OCR boom")

        proc = make_processor(
            paperless=paperless, ocr_provider=ocr_provider, settings=settings
        )

        proc.process()

        # A transcription failure must still release the page (closed in the
        # per-page finally).
        assert img1.close.called


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
    @patch("ocr.worker.open_page_source", return_value=PageSource(images=[]))
    def test_no_pages_returns_early(self, mock_open_pages, mock_claim, mock_release):
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


class TestProcessSkipsBornDigital:
    def test_process_skips_born_digital_end_to_end(self):
        proc = make_processor(OCR_SKIP_BORN_DIGITAL=True, OCR_PROCESSING_TAG_ID=999)
        proc.paperless_client.get_document.return_value = make_document(
            mime_type="application/pdf",
            content="real text " * 50,
            tags=[proc.settings.PRE_TAG_ID],
        )
        proc.paperless_client.download_original.return_value = (
            b"%PDF",
            "application/pdf",
        )
        with (
            patch(
                "ocr.worker.classify_original",
                return_value=BornDigitalDecision(True, "born-digital", {}),
            ),
            patch(
                "ocr.worker.get_latest_tags",
                return_value={proc.settings.PRE_TAG_ID},
            ),
            patch("ocr.worker.claim_processing_tag", return_value=True),
            patch("ocr.worker.release_processing_tag") as release,
        ):
            outcome = proc.process()
        assert outcome is None  # breaker-neutral
        assert proc.ocr_provider.transcribe_image.call_count == 0
        release.assert_called_once()  # processing tag released
