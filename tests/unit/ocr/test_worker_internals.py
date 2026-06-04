"""Tests for ocr.worker — the per-method helpers of ``OcrProcessor``.

Covers parallel page OCR, the Paperless content update, error finalisation,
and stats logging.  Split from ``test_worker`` (the ``process()`` lifecycle)
for the 500-line ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

from unittest.mock import patch

from ocr.image_converter import PageSource
from ocr.text_assembly import OCR_ERROR_MARKER, PageResult
from tests.helpers.factories import make_settings_obj
from tests.helpers.mocks import make_mock_ocr_provider, make_mock_paperless
from tests.unit.ocr.conftest import make_image, make_page_source, make_processor


class TestOcrPagesInParallel:
    def test_preserves_page_order(self):
        # Arrange — single worker for deterministic side_effect ordering
        settings = make_settings_obj(PAGE_WORKERS=1)
        ocr_provider = make_mock_ocr_provider()
        ocr_provider.transcribe_image.side_effect = [
            PageResult("Text page 1", "m"),
            PageResult("Text page 2", "m"),
            PageResult("Text page 3", "m"),
        ]
        proc = make_processor(ocr_provider=ocr_provider, settings=settings)
        pages = make_page_source([make_image() for _ in range(3)])

        results, failed = proc._ocr_pages_in_parallel(pages)

        # Assert — correct count, no failures, and content in correct order
        assert len(results) == 3
        assert failed == []
        assert results[0] == PageResult("Text page 1", "m")
        assert results[1] == PageResult("Text page 2", "m")
        assert results[2] == PageResult("Text page 3", "m")

    def test_handles_ocr_exception_per_page(self):
        settings = make_settings_obj(PAGE_WORKERS=1)
        ocr_provider = make_mock_ocr_provider()
        ocr_provider.transcribe_image.side_effect = [
            PageResult("Text page 1", "m"),
            Exception("OCR failed on page 2"),
            PageResult("Text page 3", "m"),
        ]
        proc = make_processor(ocr_provider=ocr_provider, settings=settings)
        pages = make_page_source([make_image() for _ in range(3)])

        results, failed = proc._ocr_pages_in_parallel(pages)

        assert len(results) == 3
        assert 2 in failed  # page 2 (1-indexed)
        assert OCR_ERROR_MARKER in results[1].text

    def test_empty_page_source(self):
        proc = make_processor()

        results, failed = proc._ocr_pages_in_parallel(PageSource(images=[]))

        assert results == []
        assert failed == []


class TestUpdatePaperlessDocumentHappy:
    @patch("ocr.worker.get_latest_tags")
    def test_happy_path_swaps_tags(self, mock_get_tags):
        settings = make_settings_obj(
            PRE_TAG_ID=443,
            POST_TAG_ID=444,
            OCR_PROCESSING_TAG_ID=999,
        )
        paperless = make_mock_paperless()
        mock_get_tags.return_value = {443, 999, 100}  # user tag 100

        proc = make_processor(paperless=paperless, settings=settings)

        proc._update_paperless_document("Good OCR text", {"model-a"})

        paperless.update_document.assert_called_once()
        args = paperless.update_document.call_args
        doc_id, text, tags = args[0]
        assert doc_id == 1
        assert text == "Good OCR text"
        tag_set = set(tags)
        assert 443 not in tag_set  # pre removed
        assert 999 not in tag_set  # processing removed
        assert 444 in tag_set  # post added
        assert 100 in tag_set  # user tag preserved


class TestUpdatePaperlessDocumentErrors:
    @patch("ocr.worker.get_latest_tags", return_value={443})
    @patch("common.tags.clean_pipeline_tags", return_value=set())
    def test_empty_text_marks_error(self, mock_clean, mock_get_tags):
        settings = make_settings_obj(ERROR_TAG_ID=552)
        paperless = make_mock_paperless()
        proc = make_processor(paperless=paperless, settings=settings)

        proc._update_paperless_document("   ", set())

        # Assert — finalise_with_error calls update_document with error tag
        paperless.update_document.assert_called_once()
        tags_arg = paperless.update_document.call_args[0][2]
        assert 552 in tags_arg

    @patch("ocr.worker.get_latest_tags", return_value={443})
    @patch("common.tags.clean_pipeline_tags", return_value=set())
    def test_ocr_error_marker_in_text_marks_error(self, mock_clean, mock_get_tags):
        settings = make_settings_obj(ERROR_TAG_ID=552)
        paperless = make_mock_paperless()
        proc = make_processor(paperless=paperless, settings=settings)

        proc._update_paperless_document(f"Some text {OCR_ERROR_MARKER} more", {"m"})

        # Assert — finalise_with_error calls update_document with error tag
        paperless.update_document.assert_called_once()
        tags_arg = paperless.update_document.call_args[0][2]
        assert 552 in tags_arg

    @patch("ocr.worker.get_latest_tags", return_value={443})
    @patch("common.tags.clean_pipeline_tags", return_value=set())
    def test_refusal_mark_in_text_marks_error(self, mock_clean, mock_get_tags):
        settings = make_settings_obj(
            ERROR_TAG_ID=552,
            REFUSAL_MARK="CHATGPT REFUSED TO TRANSCRIBE",
        )
        paperless = make_mock_paperless()
        proc = make_processor(paperless=paperless, settings=settings)

        proc._update_paperless_document("CHATGPT REFUSED TO TRANSCRIBE", set())

        # Assert — finalise_with_error calls update_document with error tag
        paperless.update_document.assert_called_once()
        tags_arg = paperless.update_document.call_args[0][2]
        assert 552 in tags_arg

    @patch("ocr.worker.get_latest_tags", return_value={443})
    @patch("common.tags.clean_pipeline_tags", return_value=set())
    def test_redacted_marker_in_text_marks_error(self, mock_clean, mock_get_tags):
        settings = make_settings_obj(ERROR_TAG_ID=552)
        paperless = make_mock_paperless()
        proc = make_processor(paperless=paperless, settings=settings)

        proc._update_paperless_document("Name: [REDACTED]", {"m"})

        # Assert — finalise_with_error calls update_document with error tag
        paperless.update_document.assert_called_once()
        tags_arg = paperless.update_document.call_args[0][2]
        assert 552 in tags_arg


class TestFinaliseWithError:
    @patch("common.tags.clean_pipeline_tags")
    def test_adds_error_tag(self, mock_clean):
        mock_clean.return_value = {100}  # user tag preserved
        settings = make_settings_obj(ERROR_TAG_ID=552)
        paperless = make_mock_paperless()
        proc = make_processor(paperless=paperless, settings=settings)

        proc._finalise_with_error({443, 100})

        paperless.update_document_metadata.assert_called_once()
        call_tags = set(paperless.update_document_metadata.call_args[1]["tags"])
        assert 552 in call_tags  # error tag added
        assert 100 in call_tags  # user tag preserved

    @patch("common.tags.clean_pipeline_tags")
    def test_no_error_tag_configured(self, mock_clean):
        mock_clean.return_value = {100}
        settings = make_settings_obj(ERROR_TAG_ID=None)
        paperless = make_mock_paperless()
        proc = make_processor(paperless=paperless, settings=settings)

        proc._finalise_with_error({443, 100})

        paperless.update_document_metadata.assert_called_once()
        call_tags = set(paperless.update_document_metadata.call_args[1]["tags"])
        assert 100 in call_tags

    @patch("common.tags.clean_pipeline_tags")
    def test_with_content_updates_document(self, mock_clean):
        mock_clean.return_value = {552}
        settings = make_settings_obj(ERROR_TAG_ID=552)
        paperless = make_mock_paperless()
        proc = make_processor(paperless=paperless, settings=settings)

        proc._finalise_with_error({443}, content="Error OCR text")

        # Assert — uses update_document (not update_document_metadata)
        paperless.update_document.assert_called_once()
        args = paperless.update_document.call_args[0]
        assert args[1] == "Error OCR text"

    @patch("common.tags.clean_pipeline_tags")
    def test_without_content_uses_metadata_update(self, mock_clean):
        mock_clean.return_value = set()
        settings = make_settings_obj(ERROR_TAG_ID=None)
        paperless = make_mock_paperless()
        proc = make_processor(paperless=paperless, settings=settings)

        proc._finalise_with_error({443})

        paperless.update_document_metadata.assert_called_once()
        paperless.update_document.assert_not_called()


class TestLogOcrStats:
    @patch("ocr.worker.log")
    def test_normal_stats_logged(self, mock_log):
        ocr_provider = make_mock_ocr_provider()
        ocr_provider.get_stats.return_value = {
            "attempts": 5,
            "refusals": 1,
            "api_errors": 0,
            "fallback_successes": 1,
        }
        proc = make_processor(ocr_provider=ocr_provider)

        proc._log_ocr_stats()

        ocr_provider.get_stats.assert_called_once()
        mock_log.info.assert_called_once()
        log_kwargs = mock_log.info.call_args.kwargs
        assert log_kwargs["attempts"] == 5

    @patch("ocr.worker.log")
    def test_zero_attempts_not_logged(self, mock_log):
        ocr_provider = make_mock_ocr_provider()
        ocr_provider.get_stats.return_value = {
            "attempts": 0,
            "refusals": 0,
            "api_errors": 0,
            "fallback_successes": 0,
        }
        proc = make_processor(ocr_provider=ocr_provider)

        proc._log_ocr_stats()

        # Assert — stats fetched but NOT logged (zero attempts)
        ocr_provider.get_stats.assert_called_once()
        mock_log.info.assert_not_called()

    def test_empty_stats_dict(self):
        ocr_provider = make_mock_ocr_provider()
        ocr_provider.get_stats.return_value = {}
        proc = make_processor(ocr_provider=ocr_provider)

        # Act — should not raise (empty dict is falsy -> returns early)
        proc._log_ocr_stats()
