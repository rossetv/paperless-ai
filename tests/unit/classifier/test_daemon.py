"""Tests for classifier.daemon."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from classifier.daemon import (
    _DaemonState,
    _iter_docs_to_classify,
    _process_document,
    _reload_if_changed,
    main,
)
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


class TestProcessDocument:
    """_process_document builds a ClassificationProcessor under run_per_document."""

    @patch("classifier.daemon.ClassificationProvider")
    @patch("common.per_document.PaperlessClient")
    @patch("classifier.daemon.ClassificationProcessor")
    def test_creates_provider_processor_processes_and_closes(
        self, mock_proc_cls, mock_client_cls, mock_provider_cls
    ):
        settings = _settings()
        doc = _doc(1, tags=[444])
        taxonomy_cache = MagicMock()
        client_instance = mock_client_cls.return_value
        provider_instance = mock_provider_cls.return_value
        proc_instance = mock_proc_cls.return_value

        _process_document(doc, settings, taxonomy_cache)

        mock_client_cls.assert_called_once_with(settings)
        mock_provider_cls.assert_called_once_with(settings)
        mock_proc_cls.assert_called_once_with(
            doc, client_instance, provider_instance, taxonomy_cache, settings
        )
        proc_instance.process.assert_called_once()
        client_instance.close.assert_called_once()

    @patch("classifier.daemon.ClassificationProvider")
    @patch("common.per_document.PaperlessClient")
    @patch("classifier.daemon.ClassificationProcessor")
    def test_client_closed_even_on_process_error(
        self, mock_proc_cls, mock_client_cls, mock_provider_cls
    ):
        settings = _settings()
        client_instance = mock_client_cls.return_value
        mock_proc_cls.return_value.process.side_effect = Exception("boom")

        with pytest.raises(Exception, match="boom"):
            _process_document(_doc(1, tags=[444]), settings, MagicMock())

        client_instance.close.assert_called_once()


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


class _FakeListClient:
    """Stub for the daemon's list_client whose close() is a no-op."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_reload_if_changed_swaps_state_on_a_config_change(tmp_path) -> None:
    """_reload_if_changed rebuilds the daemon state when config_version moves,
    and is a no-op when it has not."""
    from appdb import config as config_store
    from appdb.connection import connect
    from appdb.schema import ensure_schema
    from common.config import _SETTINGS_CACHE, current_settings

    app_db = str(tmp_path / "app.db")
    conn = connect(app_db)
    ensure_schema(conn)
    conn.close()
    env = {
        "APP_DB_PATH": app_db,
        "PAPERLESS_TOKEN": "t",
        "OPENAI_API_KEY": "k",
    }
    # Clear the process-local hot-load cache so the test's temp app.db is read
    # fresh and not served by an earlier test's cached entry.
    _SETTINGS_CACHE.pop(app_db, None)
    rebuilt_clients = [MagicMock(), MagicMock()]
    for client in rebuilt_clients:
        client.close = MagicMock()
    rebuilt_taxonomy_cache = MagicMock()
    with (
        patch.dict(os.environ, env, clear=True),
        patch("classifier.daemon.PaperlessClient", side_effect=rebuilt_clients),
        patch("classifier.daemon.TaxonomyCache", return_value=rebuilt_taxonomy_cache),
        patch("classifier.daemon.configure_logging"),
        patch("classifier.daemon.setup_libraries"),
        patch("classifier.daemon.llm_limiter"),
    ):
        settings = current_settings(app_db)
        list_client = _FakeListClient()
        taxonomy_client = _FakeListClient()
        taxonomy_cache = MagicMock()
        state = _DaemonState(
            settings=settings,
            list_client=list_client,
            taxonomy_client=taxonomy_client,
            taxonomy_cache=taxonomy_cache,
            app_db_path=app_db,
        )
        # No config change — _reload_if_changed leaves state.settings as-is.
        _reload_if_changed(state)
        assert state.settings is settings
        assert state.list_client is list_client
        assert list_client.closed is False
        assert taxonomy_client.closed is False
        # A config write bumps config_version; the hook swaps state.settings.
        c = connect(app_db)
        config_store.set_value(c, "CLASSIFY_MAX_CHARS", "1234")
        c.close()
        _reload_if_changed(state)
    assert state.settings is not settings
    assert state.settings.CLASSIFY_MAX_CHARS == 1234
    # The previous clients were closed and replaced with the rebuilt ones.
    assert list_client.closed is True
    assert taxonomy_client.closed is True
    assert state.list_client is rebuilt_clients[0]
    assert state.taxonomy_client is rebuilt_clients[1]
    assert state.taxonomy_cache is rebuilt_taxonomy_cache
