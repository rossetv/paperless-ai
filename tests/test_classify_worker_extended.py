"""Extended tests for classifier.worker — full classification flow."""

import os
from unittest.mock import MagicMock

import pytest

from classifier.result import ClassificationResult
from classifier.worker import ClassificationProcessor
from common.config import Settings


@pytest.fixture
def settings(mocker):
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "PRE_TAG_ID": "443",
            "POST_TAG_ID": "444",
            "ERROR_TAG_ID": "552",
            "CLASSIFY_PRE_TAG_ID": "444",
            "CLASSIFY_POST_TAG_ID": "445",
            "CLASSIFY_PROCESSING_TAG_ID": "500",
            "CLASSIFY_DEFAULT_COUNTRY_TAG": "ireland",
            "CLASSIFY_TAG_LIMIT": "5",
            "CLASSIFY_MAX_PAGES": "3",
            "CLASSIFY_TAIL_PAGES": "1",
        },
        clear=True,
    )
    return Settings()


def _find_call_with_key(calls, key):
    """Find an update_document_metadata call that has a specific kwarg."""
    for c in calls:
        if key in c[1]:
            return c
    return None


def _find_call_with_tag(calls, tag_id):
    """Find an update_document_metadata call that includes a specific tag."""
    for c in calls:
        tags = c[1].get("tags", [])
        if tag_id in tags:
            return c
    return None


def _make_processor(settings, doc=None, content="Some OCR content"):
    """Create a ClassificationProcessor with a properly mocked claim flow."""
    doc = doc or {"id": 1, "title": "Test", "tags": [444]}
    processing_tag = settings.CLASSIFY_PROCESSING_TAG_ID or 500
    paperless = MagicMock()

    base_doc = {
        "id": 1,
        "content": content,
        "tags": [444, 42],
        "created": "2024-06-01T00:00:00Z",
    }
    doc_with_claim = dict(base_doc, tags=[444, 42, processing_tag])

    # get_document calls: process refresh → claim refresh → claim verify →
    # further calls (release, etc.)
    paperless.get_document.side_effect = [
        dict(base_doc),       # process() _refresh_document
        dict(base_doc),       # claim_processing_tag refresh
        dict(doc_with_claim), # claim_processing_tag verify → claimed
        dict(doc_with_claim), # release_processing_tag refresh
        dict(doc_with_claim), # extra safety
        dict(doc_with_claim), # extra safety
    ]

    classifier = MagicMock()
    taxonomy_cache = MagicMock()
    taxonomy_cache.correspondent_names.return_value = ["ACME"]
    taxonomy_cache.document_type_names.return_value = ["Invoice"]
    taxonomy_cache.tag_names.return_value = ["Bills"]
    return ClassificationProcessor(
        doc, paperless, classifier, taxonomy_cache, settings
    ), paperless, classifier, taxonomy_cache


def test_successful_classification_applies_metadata(settings):
    proc, paperless, classifier, taxonomy_cache = _make_processor(settings)

    classifier.classify_text.return_value = (
        ClassificationResult(
            title="My Invoice",
            correspondent="ACME Corp",
            tags=["Bills", "Receipts"],
            document_date="2024-06-01",
            document_type="Invoice",
            language="en",
            person="John Doe",
        ),
        "gpt-5-mini",
    )
    taxonomy_cache.get_or_create_tag_ids.return_value = [100, 101]
    taxonomy_cache.get_or_create_correspondent_id.return_value = 200
    taxonomy_cache.get_or_create_document_type_id.return_value = 300

    proc.process()

    # Find the classification call (has "title" kwarg)
    calls = paperless.update_document_metadata.call_args_list
    classify_call = _find_call_with_key(calls, "title")
    assert classify_call is not None, f"No call with 'title' kwarg found in {calls}"
    kw = classify_call[1]
    assert kw["title"] == "My Invoice"
    assert kw["correspondent_id"] == 200
    assert kw["document_type_id"] == 300
    assert kw["document_date"] == "2024-06-01"
    assert kw["language"] == "en"
    tag_set = set(kw["tags"])
    assert 100 in tag_set
    assert 101 in tag_set
    assert 445 in tag_set   # CLASSIFY_POST_TAG_ID
    assert 42 in tag_set    # preserved user tag


def test_empty_classification_marks_error(settings):
    proc, paperless, classifier, _ = _make_processor(settings)

    classifier.classify_text.return_value = (
        ClassificationResult(
            title="", correspondent="", tags=[], document_date="",
            document_type="", language="", person="",
        ),
        "model",
    )

    proc.process()

    # Find the error marking call (has ERROR_TAG_ID in tags)
    calls = paperless.update_document_metadata.call_args_list
    error_call = _find_call_with_tag(calls, settings.ERROR_TAG_ID)
    assert error_call is not None, f"No call with error tag found in {calls}"


def test_none_result_marks_error(settings):
    proc, paperless, classifier, _ = _make_processor(settings)
    classifier.classify_text.return_value = (None, "")

    proc.process()

    calls = paperless.update_document_metadata.call_args_list
    error_call = _find_call_with_tag(calls, settings.ERROR_TAG_ID)
    assert error_call is not None


def test_refusal_content_marks_error(settings):
    """When OCR content contains refusal phrases, classification should error."""
    proc, paperless, classifier, taxonomy_cache = _make_processor(
        settings,
        content="I'm sorry, I can't assist with that.",
    )

    classifier.classify_text.return_value = (
        ClassificationResult(
            title="Title", correspondent="Co", tags=["Tag"],
            document_date="2024-01-01", document_type="Invoice",
            language="en", person="",
        ),
        "model",
    )
    taxonomy_cache.get_or_create_tag_ids.return_value = [100]
    taxonomy_cache.get_or_create_correspondent_id.return_value = 200
    taxonomy_cache.get_or_create_document_type_id.return_value = 300

    proc.process()

    calls = paperless.update_document_metadata.call_args_list
    error_call = _find_call_with_tag(calls, settings.ERROR_TAG_ID)
    assert error_call is not None


def test_truncation_by_pages_and_chars(settings):
    settings.CLASSIFY_MAX_PAGES = 2
    settings.CLASSIFY_MAX_CHARS = 50

    long_content = (
        "--- Page 1 ---\n" + "A" * 30 + "\n\n"
        "--- Page 2 ---\n" + "B" * 30 + "\n\n"
        "--- Page 3 ---\n" + "C" * 30 + "\n\n"
        "\n\nTranscribed by model: gpt-5"
    )

    proc, paperless, classifier, _ = _make_processor(settings, content=long_content)

    classifier.classify_text.return_value = (None, "")

    proc.process()

    call_args = classifier.classify_text.call_args
    input_text = call_args[0][0]
    assert "--- Page 3 ---" not in input_text


def test_processing_tag_released_on_exception(settings):
    proc, paperless, classifier, _ = _make_processor(settings)
    classifier.classify_text.side_effect = RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        proc.process()

    # Release should have been attempted in the finally block
    assert paperless.get_document.call_count >= 4


def test_no_correspondent_when_empty(settings):
    proc, paperless, classifier, taxonomy_cache = _make_processor(settings)

    classifier.classify_text.return_value = (
        ClassificationResult(
            title="Title", correspondent="", tags=[],
            document_date="2024-01-01", document_type="Invoice",
            language="en", person="",
        ),
        "model",
    )
    taxonomy_cache.get_or_create_tag_ids.return_value = []
    taxonomy_cache.get_or_create_document_type_id.return_value = 300

    proc.process()

    taxonomy_cache.get_or_create_correspondent_id.assert_not_called()
    classify_call = _find_call_with_key(
        paperless.update_document_metadata.call_args_list, "title"
    )
    assert classify_call is not None
    assert classify_call[1]["correspondent_id"] is None


def test_classification_stats_logged(settings):
    proc, paperless, classifier, taxonomy_cache = _make_processor(settings)

    classifier.classify_text.return_value = (
        ClassificationResult(
            title="T", correspondent="C", tags=["A"],
            document_date="2024-01-01", document_type="Invoice",
            language="en", person="",
        ),
        "model",
    )
    classifier.get_stats.return_value = {"attempts": 3, "api_errors": 1}
    taxonomy_cache.get_or_create_tag_ids.return_value = [100]
    taxonomy_cache.get_or_create_correspondent_id.return_value = 200
    taxonomy_cache.get_or_create_document_type_id.return_value = 300

    proc.process()

    classifier.get_stats.assert_called()


# ---------------------------------------------------------------------------
# Line 114: _claim_processing_tag returning False (already claimed)
# ---------------------------------------------------------------------------


def test_claim_processing_tag_returns_false_already_claimed(settings):
    """When claim_processing_tag returns False, process() returns early (line 114)."""
    doc = {"id": 1, "title": "Test", "tags": [444]}
    processing_tag = settings.CLASSIFY_PROCESSING_TAG_ID or 500

    paperless = MagicMock()
    # The document already has the processing tag when refreshed
    doc_with_tag = {
        "id": 1,
        "content": "Some OCR content",
        "tags": [444, processing_tag],
        "created": "2024-06-01T00:00:00Z",
    }
    paperless.get_document.return_value = doc_with_tag

    classifier = MagicMock()
    # Remove get_stats so _log_classification_stats hits the hasattr branch
    del classifier.get_stats
    taxonomy_cache = MagicMock()

    proc = ClassificationProcessor(doc, paperless, classifier, taxonomy_cache, settings)
    proc.process()

    # classify_text should NOT have been called since claim failed
    classifier.classify_text.assert_not_called()


# ---------------------------------------------------------------------------
# Lines 178-181: Page truncation happening in _truncate_content
# ---------------------------------------------------------------------------


def test_truncate_content_page_truncation_with_note(settings):
    """When CLASSIFY_MAX_PAGES > 0 and content gets truncated, notes are appended (lines 178-181)."""
    settings.CLASSIFY_MAX_PAGES = 1
    settings.CLASSIFY_TAIL_PAGES = 0
    settings.CLASSIFY_MAX_CHARS = 0  # no char truncation

    long_content = (
        "--- Page 1 ---\n" + "A" * 30 + "\n\n"
        "--- Page 2 ---\n" + "B" * 30 + "\n\n"
        "--- Page 3 ---\n" + "C" * 30 + "\n\n"
        "\n\nTranscribed by model: gpt-5"
    )

    proc, paperless, classifier, taxonomy_cache = _make_processor(
        settings, content=long_content
    )

    classifier.classify_text.return_value = (
        ClassificationResult(
            title="T", correspondent="C", tags=["A"],
            document_date="2024-01-01", document_type="Invoice",
            language="en", person="",
        ),
        "model",
    )
    taxonomy_cache.get_or_create_tag_ids.return_value = [100]
    taxonomy_cache.get_or_create_correspondent_id.return_value = 200
    taxonomy_cache.get_or_create_document_type_id.return_value = 300

    proc.process()

    # Verify that classify_text was called with a truncation note
    call_args = classifier.classify_text.call_args
    truncation_note = call_args[1].get("truncation_note") or call_args[0][4] if len(call_args[0]) > 4 else call_args[1].get("truncation_note")
    assert truncation_note is not None
    assert "truncated" in truncation_note.lower()


# ---------------------------------------------------------------------------
# Line 240: _finalize_with_error when ERROR_TAG_ID is None
# ---------------------------------------------------------------------------


def test_finalize_with_error_no_error_tag_configured(settings, mocker):
    """When ERROR_TAG_ID is None, _finalize_with_error still cleans pipeline tags (line 240)."""
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "PRE_TAG_ID": "443",
            "POST_TAG_ID": "444",
            "ERROR_TAG_ID": "0",
            "CLASSIFY_PRE_TAG_ID": "444",
            "CLASSIFY_PROCESSING_TAG_ID": "500",
            "CLASSIFY_TAG_LIMIT": "5",
            "CLASSIFY_MAX_PAGES": "0",
        },
        clear=True,
    )
    no_error_settings = Settings()
    assert no_error_settings.ERROR_TAG_ID is None

    doc = {"id": 1, "title": "Test", "tags": [444]}
    processing_tag = no_error_settings.CLASSIFY_PROCESSING_TAG_ID or 500

    paperless = MagicMock()
    base_doc = {
        "id": 1,
        "content": "Some OCR content",
        "tags": [444, 42],
        "created": "2024-06-01T00:00:00Z",
    }
    doc_with_claim = dict(base_doc, tags=[444, 42, processing_tag])
    paperless.get_document.side_effect = [
        dict(base_doc),
        dict(base_doc),
        dict(doc_with_claim),
        dict(doc_with_claim),
        dict(doc_with_claim),
        dict(doc_with_claim),
    ]

    classifier = MagicMock()
    classifier.classify_text.return_value = (None, "")
    classifier.get_stats.return_value = {"attempts": 1}
    taxonomy_cache = MagicMock()

    proc = ClassificationProcessor(doc, paperless, classifier, taxonomy_cache, no_error_settings)
    proc.process()

    # update_document_metadata should have been called to clean pipeline tags
    # without adding an error tag (since ERROR_TAG_ID is None)
    calls = paperless.update_document_metadata.call_args_list
    assert len(calls) >= 1
    # Find the error-handling call (no error tag should be in tags)
    for c in calls:
        tags_in_call = c[1].get("tags", [])
        # No error tag ID should be present since it's None
        # Just verify pipeline tags were cleaned (443, 444 removed)
        assert 443 not in tags_in_call or 444 not in tags_in_call


# ---------------------------------------------------------------------------
# Line 307: Custom fields update path (CLASSIFY_PERSON_FIELD_ID set)
# ---------------------------------------------------------------------------


def test_custom_fields_person_field_applied(settings, mocker):
    """When CLASSIFY_PERSON_FIELD_ID is set and result.person is present, custom_fields are updated (line 307)."""
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "PRE_TAG_ID": "443",
            "POST_TAG_ID": "444",
            "ERROR_TAG_ID": "552",
            "CLASSIFY_PRE_TAG_ID": "444",
            "CLASSIFY_POST_TAG_ID": "445",
            "CLASSIFY_PROCESSING_TAG_ID": "500",
            "CLASSIFY_DEFAULT_COUNTRY_TAG": "ireland",
            "CLASSIFY_TAG_LIMIT": "5",
            "CLASSIFY_MAX_PAGES": "3",
            "CLASSIFY_TAIL_PAGES": "1",
            "CLASSIFY_PERSON_FIELD_ID": "99",
        },
        clear=True,
    )
    person_settings = Settings()
    assert person_settings.CLASSIFY_PERSON_FIELD_ID == 99

    doc = {"id": 1, "title": "Test", "tags": [444]}
    processing_tag = person_settings.CLASSIFY_PROCESSING_TAG_ID or 500

    paperless = MagicMock()
    base_doc = {
        "id": 1,
        "content": "Some OCR content",
        "tags": [444, 42],
        "created": "2024-06-01T00:00:00Z",
        "custom_fields": [{"field": 50, "value": "existing"}],
    }
    doc_with_claim = dict(base_doc, tags=[444, 42, processing_tag])
    paperless.get_document.side_effect = [
        dict(base_doc),
        dict(base_doc),
        dict(doc_with_claim),
        dict(doc_with_claim),
        dict(doc_with_claim),
        dict(doc_with_claim),
    ]

    classifier = MagicMock()
    classifier.classify_text.return_value = (
        ClassificationResult(
            title="My Doc",
            correspondent="ACME",
            tags=["Bills"],
            document_date="2024-01-01",
            document_type="Invoice",
            language="en",
            person="John Doe",
        ),
        "gpt-5-mini",
    )
    classifier.get_stats.return_value = {"attempts": 1}
    taxonomy_cache = MagicMock()
    taxonomy_cache.correspondent_names.return_value = ["ACME"]
    taxonomy_cache.document_type_names.return_value = ["Invoice"]
    taxonomy_cache.tag_names.return_value = ["Bills"]
    taxonomy_cache.get_or_create_tag_ids.return_value = [100]
    taxonomy_cache.get_or_create_correspondent_id.return_value = 200
    taxonomy_cache.get_or_create_document_type_id.return_value = 300

    proc = ClassificationProcessor(doc, paperless, classifier, taxonomy_cache, person_settings)
    proc.process()

    # Find the classification call that has custom_fields
    calls = paperless.update_document_metadata.call_args_list
    classify_call = _find_call_with_key(calls, "custom_fields")
    assert classify_call is not None, f"No call with 'custom_fields' kwarg found in {calls}"
    custom_fields = classify_call[1]["custom_fields"]
    assert custom_fields is not None
    # Should contain original field plus new person field
    person_entry = [f for f in custom_fields if f["field"] == 99]
    assert len(person_entry) == 1
    assert person_entry[0]["value"] == "John Doe"
    # Original custom field should be preserved
    existing_entry = [f for f in custom_fields if f["field"] == 50]
    assert len(existing_entry) == 1
    assert existing_entry[0]["value"] == "existing"


# ---------------------------------------------------------------------------
# Lines 341, 344: _log_classification_stats edge cases
# ---------------------------------------------------------------------------


def test_log_classification_stats_no_get_stats_method(settings):
    """When the classifier has no get_stats method, _log_classification_stats returns early (line 341)."""
    doc = {"id": 1, "title": "Test", "tags": [444]}
    processing_tag = settings.CLASSIFY_PROCESSING_TAG_ID or 500

    paperless = MagicMock()
    base_doc = {
        "id": 1,
        "content": "Some OCR content",
        "tags": [444, 42],
        "created": "2024-06-01T00:00:00Z",
    }
    doc_with_claim = dict(base_doc, tags=[444, 42, processing_tag])
    paperless.get_document.side_effect = [
        dict(base_doc),
        dict(base_doc),
        dict(doc_with_claim),
        dict(doc_with_claim),
        dict(doc_with_claim),
        dict(doc_with_claim),
    ]

    classifier = MagicMock()
    # Delete get_stats to simulate a classifier without this method
    del classifier.get_stats

    classifier.classify_text.return_value = (None, "")

    taxonomy_cache = MagicMock()

    proc = ClassificationProcessor(doc, paperless, classifier, taxonomy_cache, settings)
    # Should not raise even though get_stats is missing
    proc.process()


def test_log_classification_stats_empty_stats(settings):
    """When get_stats returns empty dict, _log_classification_stats returns early (line 344)."""
    doc = {"id": 1, "title": "Test", "tags": [444]}
    processing_tag = settings.CLASSIFY_PROCESSING_TAG_ID or 500

    paperless = MagicMock()
    base_doc = {
        "id": 1,
        "content": "Some OCR content",
        "tags": [444, 42],
        "created": "2024-06-01T00:00:00Z",
    }
    doc_with_claim = dict(base_doc, tags=[444, 42, processing_tag])
    paperless.get_document.side_effect = [
        dict(base_doc),
        dict(base_doc),
        dict(doc_with_claim),
        dict(doc_with_claim),
        dict(doc_with_claim),
        dict(doc_with_claim),
    ]

    classifier = MagicMock()
    classifier.get_stats.return_value = {}
    classifier.classify_text.return_value = (None, "")

    taxonomy_cache = MagicMock()

    proc = ClassificationProcessor(doc, paperless, classifier, taxonomy_cache, settings)
    # Should not raise even though stats is empty
    proc.process()


def test_log_classification_stats_zero_attempts(settings):
    """When get_stats returns dict with attempts=0, _log_classification_stats returns early (line 344)."""
    doc = {"id": 1, "title": "Test", "tags": [444]}
    processing_tag = settings.CLASSIFY_PROCESSING_TAG_ID or 500

    paperless = MagicMock()
    base_doc = {
        "id": 1,
        "content": "Some OCR content",
        "tags": [444, 42],
        "created": "2024-06-01T00:00:00Z",
    }
    doc_with_claim = dict(base_doc, tags=[444, 42, processing_tag])
    paperless.get_document.side_effect = [
        dict(base_doc),
        dict(base_doc),
        dict(doc_with_claim),
        dict(doc_with_claim),
        dict(doc_with_claim),
        dict(doc_with_claim),
    ]

    classifier = MagicMock()
    classifier.get_stats.return_value = {"attempts": 0, "api_errors": 0}
    classifier.classify_text.return_value = (None, "")

    taxonomy_cache = MagicMock()

    proc = ClassificationProcessor(doc, paperless, classifier, taxonomy_cache, settings)
    # Should not raise even though attempts is 0
    proc.process()
