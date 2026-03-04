from unittest.mock import Mock

from classifier import daemon as classify_main_module


def _set_required_env(monkeypatch):
    monkeypatch.setenv("PAPERLESS_TOKEN", "test_token")
    monkeypatch.setenv("OPENAI_API_KEY", "test_api_key")
    monkeypatch.setenv("PRE_TAG_ID", "10")
    monkeypatch.setenv("POST_TAG_ID", "11")
    monkeypatch.setenv("CLASSIFY_PRE_TAG_ID", "11")
    monkeypatch.setenv("CLASSIFY_POST_TAG_ID", "12")
    monkeypatch.setenv("DOCUMENT_WORKERS", "1")


def test_classify_main_skips_docs_with_post_tag_and_cleans_stale_pre_tag(monkeypatch):
    _set_required_env(monkeypatch)

    docs = [
        {"id": 1, "tags": [11]},  # should be processed
        {"id": 2, "tags": [11, 12, 99]},  # should be skipped + pre-tag removed
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
            assert tag_id == 11
            return list(docs)

        def update_document_metadata(self, doc_id, *, tags=None, **kwargs):
            assert kwargs == {}
            self.updated_tags[doc_id] = set(tags or [])

        def close(self):
            self.closed = True

    class DummyTaxonomyCache:
        def __init__(self, client, limit):
            self.client = client
            self.limit = limit
            self.refresh_calls = 0

        def refresh(self):
            self.refresh_calls += 1

        def correspondent_names(self):
            return []

        def document_type_names(self):
            return []

        def tag_names(self):
            return []

        def get_or_create_tag_ids(self, tags):
            return []

        def get_or_create_correspondent_id(self, name):
            return None

        def get_or_create_document_type_id(self, name):
            return None

    class DummyClassifier:
        def __init__(self, settings):
            self.settings = settings

    class DummyProcessor:
        def __init__(self, doc, paperless, classifier, taxonomy_cache, settings):
            self.doc = doc

        def process(self):
            processed.append(self.doc["id"])

    def run_once(**kwargs):
        items = kwargs["fetch_work"]()
        if not items:
            return
        kwargs["before_each_batch"](items)
        for item in items:
            kwargs["process_item"](item)

    monkeypatch.setattr(classify_main_module, "PaperlessClient", DummyPaperlessClient)
    monkeypatch.setattr(classify_main_module, "TaxonomyCache", DummyTaxonomyCache)
    monkeypatch.setattr(classify_main_module, "ClassificationProvider", DummyClassifier)
    monkeypatch.setattr(classify_main_module, "ClassificationProcessor", DummyProcessor)
    monkeypatch.setattr(classify_main_module, "configure_logging", lambda settings: None)
    monkeypatch.setattr(classify_main_module, "setup_libraries", lambda settings: None)
    monkeypatch.setattr(classify_main_module, "run_preflight_checks", lambda s, c: None)
    monkeypatch.setattr(classify_main_module, "recover_stale_locks", lambda c, **kw: 0)
    monkeypatch.setattr(classify_main_module, "run_polling_threadpool", run_once)

    classify_main_module.main()

    assert processed == [1]
    assert len(DummyPaperlessClient.instances) == 3  # list + taxonomy + per-doc
    assert DummyPaperlessClient.instances[0].updated_tags[2] == {12, 99}
    assert all(client.closed for client in DummyPaperlessClient.instances)


# ---------------------------------------------------------------------------
# Tests for _iter_docs_to_classify — lines 44-45, 66
# ---------------------------------------------------------------------------


def _make_classify_settings(**overrides):
    """Build a minimal mock Settings for _iter_docs_to_classify."""
    s = Mock()
    s.CLASSIFY_PRE_TAG_ID = overrides.get("CLASSIFY_PRE_TAG_ID", 11)
    s.CLASSIFY_POST_TAG_ID = overrides.get("CLASSIFY_POST_TAG_ID", 12)
    s.CLASSIFY_PROCESSING_TAG_ID = overrides.get("CLASSIFY_PROCESSING_TAG_ID", None)
    return s


def test_iter_docs_to_classify_skips_doc_without_integer_id():
    """Lines 44-45: documents whose 'id' is not an int are warned and skipped."""
    mock_client = Mock()
    mock_client.get_documents_by_tag.return_value = [
        {"tags": [11]},                       # missing id entirely
        {"id": None, "tags": [11]},            # id is None
        {"id": "abc", "tags": [11]},           # id is a string
        {"id": 1, "tags": [11]},               # valid — should be yielded
    ]
    settings = _make_classify_settings()

    results = list(classify_main_module._iter_docs_to_classify(mock_client, settings))

    assert len(results) == 1
    assert results[0]["id"] == 1


def test_iter_docs_to_classify_skips_doc_claimed_by_processing_tag():
    """Line 66: documents already carrying CLASSIFY_PROCESSING_TAG_ID are skipped."""
    processing_tag = 60
    mock_client = Mock()
    mock_client.get_documents_by_tag.return_value = [
        {"id": 1, "tags": [11, processing_tag]},  # already claimed — skip
        {"id": 2, "tags": [11]},                   # not claimed — yield
    ]
    settings = _make_classify_settings(CLASSIFY_PROCESSING_TAG_ID=processing_tag)

    results = list(classify_main_module._iter_docs_to_classify(mock_client, settings))

    assert len(results) == 1
    assert results[0]["id"] == 2


# ---------------------------------------------------------------------------
# Test for main() config error — lines 84-86
# ---------------------------------------------------------------------------


def test_classify_main_exits_on_config_error(mocker, monkeypatch):
    """Lines 84-86: Settings() raises ValueError, main() logs error and returns."""
    logger = mocker.Mock()
    monkeypatch.setattr(
        classify_main_module.structlog, "get_logger", mocker.Mock(return_value=logger)
    )
    monkeypatch.setattr(
        classify_main_module, "Settings", mocker.Mock(side_effect=ValueError("bad config"))
    )
    paperless_spy = mocker.Mock()
    monkeypatch.setattr(classify_main_module, "PaperlessClient", paperless_spy)

    classify_main_module.main()

    logger.error.assert_called_once()
    paperless_spy.assert_not_called()


# Line 129: ``if __name__ == "__main__": main()`` is a standard entry-point
# guard.  It is intentionally left untested.
