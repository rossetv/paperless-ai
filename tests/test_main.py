from unittest.mock import Mock

from ocr import daemon as main_module


def _set_required_env(monkeypatch):
    monkeypatch.setenv("PAPERLESS_TOKEN", "test_token")
    monkeypatch.setenv("OPENAI_API_KEY", "test_api_key")
    monkeypatch.setenv("PRE_TAG_ID", "10")
    monkeypatch.setenv("POST_TAG_ID", "11")
    monkeypatch.setenv("DOCUMENT_WORKERS", "1")


def test_main_exits_on_config_error(mocker, monkeypatch):
    logger = mocker.Mock()
    monkeypatch.setattr(
        main_module.structlog, "get_logger", mocker.Mock(return_value=logger)
    )
    monkeypatch.setattr(main_module, "Settings", mocker.Mock(side_effect=ValueError("bad")))
    paperless_spy = mocker.Mock()
    monkeypatch.setattr(main_module, "PaperlessClient", paperless_spy)

    main_module.main()

    logger.error.assert_called_once()
    paperless_spy.assert_not_called()


def test_main_skips_docs_with_post_tag_and_cleans_stale_pre_tag(monkeypatch):
    _set_required_env(monkeypatch)

    docs = [
        {"id": 1, "tags": [10]},  # should be processed
        {"id": 2, "tags": [10, 11, 99]},  # should be skipped + pre-tag removed
    ]
    processed = []

    class DummyPaperlessClient:
        instances = []

        def __init__(self, settings):
            self.settings = settings
            self.closed = False
            self.updated_tags = {}
            DummyPaperlessClient.instances.append(self)

        def get_documents_by_tag(self, tag_id):
            assert tag_id == 10
            return list(docs)

        def update_document_metadata(self, doc_id, *, tags=None, **kwargs):
            assert kwargs == {}
            self.updated_tags[doc_id] = set(tags or [])

        def close(self):
            self.closed = True

    class DummyOpenAIProvider:
        def __init__(self, settings):
            self.settings = settings

    class DummyProcessor:
        def __init__(self, doc, paperless, ocr_provider, settings):
            self.doc = doc

        def process(self):
            processed.append(self.doc["id"])

    def run_once(**kwargs):
        items = kwargs["fetch_work"]()
        for item in items:
            kwargs["process_item"](item)

    monkeypatch.setattr(main_module, "PaperlessClient", DummyPaperlessClient)
    monkeypatch.setattr(main_module, "OpenAIProvider", DummyOpenAIProvider)
    monkeypatch.setattr(main_module, "DocumentProcessor", DummyProcessor)
    monkeypatch.setattr(main_module, "configure_logging", lambda settings: None)
    monkeypatch.setattr(main_module, "setup_libraries", lambda settings: None)
    monkeypatch.setattr(main_module, "run_preflight_checks", lambda s, c: None)
    monkeypatch.setattr(main_module, "recover_stale_locks", lambda c, **kw: 0)
    monkeypatch.setattr(main_module, "run_polling_threadpool", run_once)

    main_module.main()

    assert processed == [1]
    # instance[0] is the list client (used for tag hygiene), instance[1] is the per-doc client
    assert len(DummyPaperlessClient.instances) == 2
    assert DummyPaperlessClient.instances[0].updated_tags[2] == {11, 99}
    assert all(client.closed for client in DummyPaperlessClient.instances)


def test_main_continues_after_processing_error(monkeypatch):
    _set_required_env(monkeypatch)
    docs = [
        {"id": 1, "tags": [10]},
        {"id": 2, "tags": [10]},
    ]
    processed = []
    attempted = []

    class DummyPaperlessClient:
        instances = []

        def __init__(self, settings):
            self.settings = settings
            self.closed = False
            DummyPaperlessClient.instances.append(self)

        def get_documents_by_tag(self, tag_id):
            assert tag_id == 10
            return list(docs)

        def update_document_metadata(self, doc_id, *, tags=None, **kwargs):
            raise AssertionError("not expected")

        def close(self):
            self.closed = True

    class DummyOpenAIProvider:
        def __init__(self, settings):
            self.settings = settings

    class DummyProcessor:
        def __init__(self, doc, paperless, ocr_provider, settings):
            self.doc = doc
            attempted.append(doc["id"])

        def process(self):
            if self.doc["id"] == 1:
                raise RuntimeError("boom")
            processed.append(self.doc["id"])

    def run_once_with_exception_handling(**kwargs):
        items = kwargs["fetch_work"]()
        for item in items:
            try:
                kwargs["process_item"](item)
            except Exception:
                # run_polling_threadpool logs and continues; mimic that.
                pass

    monkeypatch.setattr(main_module, "PaperlessClient", DummyPaperlessClient)
    monkeypatch.setattr(main_module, "OpenAIProvider", DummyOpenAIProvider)
    monkeypatch.setattr(main_module, "DocumentProcessor", DummyProcessor)
    monkeypatch.setattr(main_module, "configure_logging", lambda settings: None)
    monkeypatch.setattr(main_module, "setup_libraries", lambda settings: None)
    monkeypatch.setattr(main_module, "run_preflight_checks", lambda s, c: None)
    monkeypatch.setattr(main_module, "recover_stale_locks", lambda c, **kw: 0)
    monkeypatch.setattr(main_module, "run_polling_threadpool", run_once_with_exception_handling)

    main_module.main()

    assert attempted == [1, 2]
    assert processed == [2]
    assert len(DummyPaperlessClient.instances) == 3  # list client + 2 per-doc clients
    assert all(client.closed for client in DummyPaperlessClient.instances)


# ---------------------------------------------------------------------------
# Tests for _iter_docs_to_ocr — lines 67-68, 86
# ---------------------------------------------------------------------------


def _make_ocr_settings(**overrides):
    """Build a minimal mock Settings for _iter_docs_to_ocr."""
    s = Mock()
    s.PRE_TAG_ID = overrides.get("PRE_TAG_ID", 10)
    s.POST_TAG_ID = overrides.get("POST_TAG_ID", 11)
    s.OCR_PROCESSING_TAG_ID = overrides.get("OCR_PROCESSING_TAG_ID", None)
    return s


def test_iter_docs_to_ocr_skips_doc_without_integer_id():
    """Lines 67-68: documents whose 'id' is not an int are warned and skipped."""
    mock_client = Mock()
    mock_client.get_documents_by_tag.return_value = [
        {"tags": [10]},                      # missing id entirely
        {"id": None, "tags": [10]},           # id is None
        {"id": "abc", "tags": [10]},          # id is a string
        {"id": 1, "tags": [10]},              # valid — should be yielded
    ]
    settings = _make_ocr_settings()

    results = list(main_module._iter_docs_to_ocr(mock_client, settings))

    assert len(results) == 1
    assert results[0]["id"] == 1


def test_iter_docs_to_ocr_skips_doc_claimed_by_processing_tag():
    """Line 86: documents already carrying OCR_PROCESSING_TAG_ID are skipped."""
    processing_tag = 50
    mock_client = Mock()
    mock_client.get_documents_by_tag.return_value = [
        {"id": 1, "tags": [10, processing_tag]},  # already claimed — skip
        {"id": 2, "tags": [10]},                   # not claimed — yield
    ]
    settings = _make_ocr_settings(OCR_PROCESSING_TAG_ID=processing_tag)

    results = list(main_module._iter_docs_to_ocr(mock_client, settings))

    assert len(results) == 1
    assert results[0]["id"] == 2


# Line 136: ``if __name__ == "__main__": main()`` is a standard entry-point
# guard.  It is intentionally left untested.
