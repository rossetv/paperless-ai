"""Tests for classifier.daemon."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from classifier.daemon import _iter_docs_to_classify, main
from tests.helpers.factories import make_document, make_settings_obj
from tests.helpers.mocks import make_mock_paperless

def _settings(**overrides):
    return make_settings_obj(**overrides)

def _doc(id, tags=None):
    """Shorthand for a document dict."""
    return make_document(id=id, tags=tags or [])

class TestMainConfigError:
    """main() with a config error exits gracefully."""

    @patch("classifier.daemon.bootstrap_daemon", return_value=None)
    def test_returns_on_config_error(self, mock_bootstrap):
        result = main()

        assert result is None
        mock_bootstrap.assert_called_once()

    @patch("classifier.daemon.bootstrap_daemon", return_value=None)
    @patch("classifier.daemon.run_polling_threadpool")
    def test_does_not_start_loop_on_config_error(self, mock_loop, mock_bootstrap):
        main()

        mock_loop.assert_not_called()

class TestIterDocsToClassifyValid:
    """Yields documents that pass all filter checks."""

    def test_yields_valid_document(self):
        client = make_mock_paperless()
        settings = _settings(
            CLASSIFY_PRE_TAG_ID=444,
            CLASSIFY_POST_TAG_ID=555,
            CLASSIFY_PROCESSING_TAG_ID=666,
        )
        doc = _doc(1, tags=[444])
        client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_classify(client, settings))

        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_yields_multiple_valid_documents(self):
        client = make_mock_paperless()
        settings = _settings(
            CLASSIFY_PRE_TAG_ID=444,
            CLASSIFY_POST_TAG_ID=555,
            CLASSIFY_PROCESSING_TAG_ID=666,
        )
        docs = [_doc(1, tags=[444]), _doc(2, tags=[444]), _doc(3, tags=[444])]
        client.get_documents_by_tag.return_value = docs

        result = list(_iter_docs_to_classify(client, settings))

        assert len(result) == 3

class TestIterDocsSkipsNonIntegerId:
    """Documents without an integer id are skipped."""

    def test_skips_none_id(self):
        client = make_mock_paperless()
        settings = _settings(CLASSIFY_PRE_TAG_ID=444, CLASSIFY_POST_TAG_ID=None)
        doc = {"id": None, "tags": [444]}
        client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_classify(client, settings))

        assert result == []

    def test_skips_string_id(self):
        client = make_mock_paperless()
        settings = _settings(CLASSIFY_PRE_TAG_ID=444, CLASSIFY_POST_TAG_ID=None)
        doc = {"id": "abc", "tags": [444]}
        client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_classify(client, settings))

        assert result == []

    def test_skips_missing_id(self):
        client = make_mock_paperless()
        settings = _settings(CLASSIFY_PRE_TAG_ID=444, CLASSIFY_POST_TAG_ID=None)
        doc = {"tags": [444]}
        client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_classify(client, settings))

        assert result == []

class TestIterDocsSkipsAlreadyClassified:
    """Documents with the post tag are skipped and stale pre-tag removed."""

    def test_skips_doc_with_post_tag(self):
        client = make_mock_paperless()
        settings = _settings(
            CLASSIFY_PRE_TAG_ID=444,
            CLASSIFY_POST_TAG_ID=555,
            CLASSIFY_PROCESSING_TAG_ID=666,
        )
        doc = _doc(1, tags=[444, 555])
        client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_classify(client, settings))

        assert result == []

    @patch("common.document_iter.remove_stale_queue_tag")
    def test_removes_stale_pre_tag(self, mock_remove):
        client = make_mock_paperless()
        settings = _settings(
            CLASSIFY_PRE_TAG_ID=444,
            CLASSIFY_POST_TAG_ID=555,
            CLASSIFY_PROCESSING_TAG_ID=666,
        )
        doc = _doc(1, tags=[444, 555])
        client.get_documents_by_tag.return_value = [doc]

        list(_iter_docs_to_classify(client, settings))

        mock_remove.assert_called_once_with(
            client,
            1,
            {444, 555},
            pre_tag_id=444,
            processing_tag_id=666,
        )

    def test_skips_post_tag_without_pre_tag_in_tag_set(self):
        """Document has post tag but not pre tag — still skipped."""
        client = make_mock_paperless()
        settings = _settings(
            CLASSIFY_PRE_TAG_ID=444,
            CLASSIFY_POST_TAG_ID=555,
            CLASSIFY_PROCESSING_TAG_ID=None,
        )
        # The document is returned by get_documents_by_tag(444) but tags
        # field shows both 444 and 555
        doc = _doc(1, tags=[444, 555])
        client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_classify(client, settings))

        assert result == []

class TestIterDocsSkipsAlreadyClaimed:
    """Documents already claimed (processing tag present) are skipped."""

    def test_skips_doc_with_processing_tag(self):
        client = make_mock_paperless()
        settings = _settings(
            CLASSIFY_PRE_TAG_ID=444,
            CLASSIFY_POST_TAG_ID=555,
            CLASSIFY_PROCESSING_TAG_ID=666,
        )
        doc = _doc(1, tags=[444, 666])
        client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_classify(client, settings))

        assert result == []

    def test_not_skipped_when_processing_tag_not_configured(self):
        """No processing tag configured means no skip."""
        client = make_mock_paperless()
        settings = _settings(
            CLASSIFY_PRE_TAG_ID=444,
            CLASSIFY_POST_TAG_ID=555,
            CLASSIFY_PROCESSING_TAG_ID=None,
        )
        doc = _doc(1, tags=[444])
        client.get_documents_by_tag.return_value = [doc]

        result = list(_iter_docs_to_classify(client, settings))

        assert len(result) == 1

class TestProcessDocumentClosure:
    """The process_document closure creates client, provider, processes, closes."""

    @patch("classifier.daemon.bootstrap_daemon")
    @patch("classifier.daemon.run_polling_threadpool")
    @patch("classifier.daemon.PaperlessClient")
    @patch("classifier.daemon.ClassificationProvider")
    @patch("classifier.daemon.TaxonomyCache")
    def test_process_document_creates_and_closes_client(
        self,
        mock_taxonomy_cls,
        mock_provider_cls,
        mock_client_cls,
        mock_loop,
        mock_bootstrap,
    ):
        settings = _settings()
        list_client = make_mock_paperless()
        mock_bootstrap.return_value = (settings, list_client)

        # Capture the process_item callable from run_polling_threadpool
        captured_process = None

        def capture_loop(**kwargs):
            nonlocal captured_process
            captured_process = kwargs["process_item"]
            # Don't actually loop

        mock_loop.side_effect = capture_loop

        # Build mock instances
        mock_paperless_instance = make_mock_paperless()
        # PaperlessClient is called for taxonomy_client and then per-doc
        mock_client_cls.side_effect = [MagicMock(), mock_paperless_instance]

        main()

        assert captured_process is not None

        # Now invoke it to test the closure
        mock_client_cls.reset_mock()
        mock_client_cls.return_value = mock_paperless_instance

        with patch("classifier.daemon.ClassificationProcessor") as mock_proc_cls:
            mock_proc_instance = MagicMock()
            mock_proc_cls.return_value = mock_proc_instance

            doc = _doc(1, tags=[444])
            captured_process(doc)

            mock_client_cls.assert_called_once()
            mock_paperless_instance.close.assert_called_once()
            mock_proc_instance.process.assert_called_once()

class TestTaxonomyRefreshAsBatchHook:
    """TaxonomyCache.refresh is passed as before_each_batch."""

    @patch("classifier.daemon.bootstrap_daemon")
    @patch("classifier.daemon.run_polling_threadpool")
    @patch("classifier.daemon.PaperlessClient")
    @patch("classifier.daemon.TaxonomyCache")
    def test_before_each_batch_calls_refresh(
        self,
        mock_taxonomy_cls,
        mock_client_cls,
        mock_loop,
        mock_bootstrap,
    ):
        settings = _settings()
        list_client = make_mock_paperless()
        mock_bootstrap.return_value = (settings, list_client)

        taxonomy_instance = MagicMock()
        mock_taxonomy_cls.return_value = taxonomy_instance

        captured_before_batch = None

        def capture_loop(**kwargs):
            nonlocal captured_before_batch
            captured_before_batch = kwargs.get("before_each_batch")

        mock_loop.side_effect = capture_loop

        mock_client_cls.return_value = MagicMock()

        main()

        assert captured_before_batch is not None
        # Call the hook — it should invoke taxonomy_cache.refresh()
        captured_before_batch([_doc(1)])
        taxonomy_instance.refresh.assert_called_once()

class TestMainCleanup:
    """Clients are closed on exit."""

    @patch("classifier.daemon.bootstrap_daemon")
    @patch("classifier.daemon.run_polling_threadpool", side_effect=KeyboardInterrupt)
    @patch("classifier.daemon.PaperlessClient")
    @patch("classifier.daemon.TaxonomyCache")
    def test_clients_closed_on_keyboard_interrupt(
        self,
        mock_taxonomy_cls,
        mock_client_cls,
        mock_loop,
        mock_bootstrap,
    ):
        settings = _settings()
        list_client = make_mock_paperless()
        mock_bootstrap.return_value = (settings, list_client)
        taxonomy_client = MagicMock()
        mock_client_cls.return_value = taxonomy_client

        with pytest.raises(KeyboardInterrupt):
            main()

        list_client.close.assert_called_once()
        taxonomy_client.close.assert_called_once()
