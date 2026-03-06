"""Tests for ocr.daemon."""

from __future__ import annotations

import unittest.mock
from unittest.mock import MagicMock, patch

import pytest

from ocr.daemon import main, _iter_docs_to_ocr, _process_document

def _make_settings(**overrides):
    from tests.helpers.factories import make_settings_obj
    return make_settings_obj(**overrides)

def _make_mock_paperless(**overrides):
    from tests.helpers.mocks import make_mock_paperless
    return make_mock_paperless(**overrides)

class TestMain:
    @patch("ocr.daemon.bootstrap_daemon", return_value=None)
    def test_config_error_returns(self, mock_bootstrap):
        result = main()

        assert result is None
        mock_bootstrap.assert_called_once_with(
            processing_tag_id=unittest.mock.ANY,
            pre_tag_id=unittest.mock.ANY,
        )

    @patch("ocr.daemon.run_polling_threadpool")
    @patch("ocr.daemon.bootstrap_daemon")
    def test_happy_path_enters_polling_loop(self, mock_bootstrap, mock_poll):
        settings = _make_settings()
        list_client = _make_mock_paperless()
        mock_bootstrap.return_value = (settings, list_client)

        main()

        mock_poll.assert_called_once()
        call_kwargs = mock_poll.call_args[1]
        assert call_kwargs["daemon_name"] == "ocr"
        assert call_kwargs["poll_interval_seconds"] == settings.POLL_INTERVAL
        assert call_kwargs["max_workers"] == settings.DOCUMENT_WORKERS

    @patch("ocr.daemon.run_polling_threadpool")
    @patch("ocr.daemon.bootstrap_daemon")
    def test_list_client_closed_in_finally(self, mock_bootstrap, mock_poll):
        settings = _make_settings()
        list_client = _make_mock_paperless()
        mock_bootstrap.return_value = (settings, list_client)
        mock_poll.side_effect = KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            main()

        list_client.close.assert_called_once()

    @patch("ocr.daemon.run_polling_threadpool")
    @patch("ocr.daemon.bootstrap_daemon")
    def test_list_client_closed_on_normal_exit(self, mock_bootstrap, mock_poll):
        settings = _make_settings()
        list_client = _make_mock_paperless()
        mock_bootstrap.return_value = (settings, list_client)

        main()

        list_client.close.assert_called_once()

class TestIterDocsToOcrYieldsValid:
    def test_yields_valid_document(self):
        settings = _make_settings(
            PRE_TAG_ID=443,
            POST_TAG_ID=444,
            OCR_PROCESSING_TAG_ID=None,
        )
        doc = {"id": 1, "title": "Test", "tags": [443]}
        list_client = _make_mock_paperless()
        list_client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_ocr(list_client, settings))

        assert len(result) == 1
        assert result[0] == doc

    def test_yields_multiple_documents(self):
        settings = _make_settings(
            PRE_TAG_ID=443,
            POST_TAG_ID=444,
            OCR_PROCESSING_TAG_ID=None,
        )
        docs = [
            {"id": 1, "title": "Doc 1", "tags": [443]},
            {"id": 2, "title": "Doc 2", "tags": [443]},
        ]
        list_client = _make_mock_paperless()
        list_client.get_documents_by_tag.return_value = docs

        result = list(_iter_docs_to_ocr(list_client, settings))

        assert len(result) == 2

class TestIterDocsToOcrSkipsNonIntegerId:
    def test_skips_none_id(self):
        settings = _make_settings(PRE_TAG_ID=443, POST_TAG_ID=444)
        doc = {"id": None, "title": "Bad", "tags": [443]}
        list_client = _make_mock_paperless()
        list_client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_ocr(list_client, settings))

        assert result == []

    def test_skips_string_id(self):
        settings = _make_settings(PRE_TAG_ID=443, POST_TAG_ID=444)
        doc = {"id": "abc", "title": "Bad", "tags": [443]}
        list_client = _make_mock_paperless()
        list_client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_ocr(list_client, settings))

        assert result == []

    def test_skips_missing_id(self):
        settings = _make_settings(PRE_TAG_ID=443, POST_TAG_ID=444)
        doc = {"title": "No ID", "tags": [443]}
        list_client = _make_mock_paperless()
        list_client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_ocr(list_client, settings))

        assert result == []

class TestIterDocsToOcrSkipsPostTagged:
    @patch("common.document_iter.remove_stale_queue_tag")
    def test_skips_doc_with_post_tag_and_removes_stale_pre(self, mock_remove):
        settings = _make_settings(
            PRE_TAG_ID=443,
            POST_TAG_ID=444,
            OCR_PROCESSING_TAG_ID=999,
        )
        doc = {"id": 1, "title": "Done", "tags": [443, 444]}
        list_client = _make_mock_paperless()
        list_client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_ocr(list_client, settings))

        assert result == []
        mock_remove.assert_called_once_with(
            list_client,
            1,
            {443, 444},
            pre_tag_id=443,
            processing_tag_id=999,
        )

    @patch("common.document_iter.remove_stale_queue_tag")
    def test_skips_doc_with_post_tag_without_pre_tag(self, mock_remove):
        # Arrange — has post tag but not pre tag (shouldn't call remove)
        settings = _make_settings(
            PRE_TAG_ID=443,
            POST_TAG_ID=444,
            OCR_PROCESSING_TAG_ID=None,
        )
        doc = {"id": 1, "title": "Done", "tags": [444]}
        list_client = _make_mock_paperless()
        list_client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_ocr(list_client, settings))

        assert result == []
        mock_remove.assert_not_called()

class TestIterDocsToOcrSkipsClaimed:
    def test_skips_doc_with_processing_tag(self):
        settings = _make_settings(
            PRE_TAG_ID=443,
            POST_TAG_ID=444,
            OCR_PROCESSING_TAG_ID=999,
        )
        doc = {"id": 1, "title": "Claimed", "tags": [443, 999]}
        list_client = _make_mock_paperless()
        list_client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_ocr(list_client, settings))

        assert result == []

    def test_no_processing_tag_configured_does_not_skip(self):
        # Arrange — processing tag not configured, should not skip
        settings = _make_settings(
            PRE_TAG_ID=443,
            POST_TAG_ID=444,
            OCR_PROCESSING_TAG_ID=None,
        )
        doc = {"id": 1, "title": "Ready", "tags": [443]}
        list_client = _make_mock_paperless()
        list_client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_ocr(list_client, settings))

        assert len(result) == 1

class TestIterDocsToOcrMixed:
    @patch("common.document_iter.remove_stale_queue_tag")
    def test_mixed_bag_of_documents(self, mock_remove):
        settings = _make_settings(
            PRE_TAG_ID=443,
            POST_TAG_ID=444,
            OCR_PROCESSING_TAG_ID=999,
        )
        docs = [
            {"id": 1, "title": "Valid", "tags": [443]},           # valid
            {"id": None, "title": "No ID", "tags": [443]},        # skip: no int id
            {"id": 2, "title": "Done", "tags": [443, 444]},       # skip: has post tag
            {"id": 3, "title": "Claimed", "tags": [443, 999]},    # skip: claimed
            {"id": 4, "title": "Also Valid", "tags": [443]},      # valid
        ]
        list_client = _make_mock_paperless()
        list_client.get_documents_by_tag.return_value = docs

        result = list(_iter_docs_to_ocr(list_client, settings))

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 4

class TestProcessDocument:
    @patch("ocr.daemon.OcrProvider")
    @patch("ocr.daemon.PaperlessClient")
    @patch("ocr.daemon.OcrProcessor")
    def test_creates_client_provider_processes_and_closes(
        self, MockProcessor, MockClient, MockProvider
    ):
        settings = _make_settings()
        doc = {"id": 1, "title": "Test", "tags": [443]}
        mock_client_instance = MagicMock()
        MockClient.return_value = mock_client_instance
        mock_provider_instance = MagicMock()
        MockProvider.return_value = mock_provider_instance
        mock_processor_instance = MagicMock()
        MockProcessor.return_value = mock_processor_instance

        _process_document(doc, settings)

        MockClient.assert_called_once_with(settings)
        MockProvider.assert_called_once_with(settings)
        MockProcessor.assert_called_once_with(
            doc, mock_client_instance, mock_provider_instance, settings
        )
        mock_processor_instance.process.assert_called_once()
        mock_client_instance.close.assert_called_once()

    @patch("ocr.daemon.OcrProvider")
    @patch("ocr.daemon.PaperlessClient")
    @patch("ocr.daemon.OcrProcessor")
    def test_client_closed_even_on_process_error(
        self, MockProcessor, MockClient, MockProvider
    ):
        settings = _make_settings()
        doc = {"id": 1, "title": "Test", "tags": [443]}
        mock_client_instance = MagicMock()
        MockClient.return_value = mock_client_instance
        MockProvider.return_value = MagicMock()
        mock_processor_instance = MagicMock()
        mock_processor_instance.process.side_effect = Exception("Process boom")
        MockProcessor.return_value = mock_processor_instance

        with pytest.raises(Exception, match="Process boom"):
            _process_document(doc, settings)

        mock_client_instance.close.assert_called_once()

    @patch("ocr.daemon.OcrProvider")
    @patch("ocr.daemon.PaperlessClient")
    @patch("ocr.daemon.OcrProcessor")
    def test_provider_created_with_settings(
        self, MockProcessor, MockClient, MockProvider
    ):
        settings = _make_settings()
        doc = {"id": 1, "title": "T", "tags": [443]}
        MockClient.return_value = MagicMock()
        MockProvider.return_value = MagicMock()
        MockProcessor.return_value = MagicMock()

        _process_document(doc, settings)

        MockProvider.assert_called_once_with(settings)
