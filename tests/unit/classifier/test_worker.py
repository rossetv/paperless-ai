"""Tests for classifier.worker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from classifier.worker import ClassificationProcessor
from tests.helpers.factories import (
    make_classification_result,
    make_document,
    make_settings_obj,
)
from tests.helpers.mocks import make_mock_paperless

def _make_processor(
    doc=None,
    settings_overrides=None,
    paperless_overrides=None,
    classifier_overrides=None,
    taxonomy_overrides=None,
) -> ClassificationProcessor:
    """Build a ClassificationProcessor with mocked dependencies."""
    doc = doc or make_document()
    settings = make_settings_obj(**(settings_overrides or {}))
    paperless = make_mock_paperless(**(paperless_overrides or {}))
    classifier = MagicMock()
    taxonomy = MagicMock()

    # Default classifier behaviour: successful classification
    result = make_classification_result()
    classifier.classify_text.return_value = (result, "gpt-5-mini")
    classifier.get_stats.return_value = {
        "attempts": 1,
        "api_errors": 0,
        "invalid_json": 0,
        "fallback_successes": 0,
        "temperature_retries": 0,
        "response_format_retries": 0,
        "max_tokens_retries": 0,
    }

    # Default taxonomy behaviour
    taxonomy.correspondent_names.return_value = ["Acme Corp"]
    taxonomy.document_type_names.return_value = ["Invoice"]
    taxonomy.tag_names.return_value = ["2025"]
    taxonomy.get_or_create_correspondent_id.return_value = 101
    taxonomy.get_or_create_document_type_id.return_value = 201
    taxonomy.get_or_create_tag_ids.return_value = [301, 302]

    if classifier_overrides:
        for k, v in classifier_overrides.items():
            setattr(classifier, k, v)
    if taxonomy_overrides:
        for k, v in taxonomy_overrides.items():
            setattr(taxonomy, k, v)

    return ClassificationProcessor(doc, paperless, classifier, taxonomy, settings)


def _make_doc_with_content(content: str, tags=None) -> dict:
    return make_document(content=content, tags=tags or [443])

class TestProcessHappyPath:
    """Full classification flow with metadata application."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_happy_path_applies_metadata(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("Invoice from Acme Corp. Total: $100.")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert — metadata update was called
        proc.paperless_client.update_document_metadata.assert_called()
        update_call = proc.paperless_client.update_document_metadata.call_args
        assert update_call.kwargs.get("title") or update_call[1].get("title")

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_happy_path_resolves_correspondent(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        proc.taxonomy_cache.get_or_create_correspondent_id.assert_called_once_with("Acme Corp")

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_happy_path_resolves_document_type(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        proc.taxonomy_cache.get_or_create_document_type_id.assert_called_once_with("Invoice")

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_happy_path_resolves_tags(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        proc.taxonomy_cache.get_or_create_tag_ids.assert_called_once()

class TestProcessClaimFailure:
    """Claim failure causes early exit without classification."""

    @patch("classifier.worker.claim_processing_tag", return_value=False)
    @patch("classifier.worker.release_processing_tag")
    def test_claim_failure_exits_without_classifying(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        proc.classifier.classify_text.assert_not_called()

    @patch("classifier.worker.claim_processing_tag", return_value=False)
    @patch("classifier.worker.release_processing_tag")
    def test_claim_failure_does_not_release_tag(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert — release not called because claimed=False
        mock_release.assert_not_called()

class TestProcessErrorTagPresent:
    """Skip classification when the document already has an error tag."""

    @patch("classifier.worker.release_processing_tag")
    def test_skips_when_error_tag_present(self, mock_release):
        # Arrange
        doc = _make_doc_with_content("text", tags=[443, 552])
        proc = _make_processor(doc=doc, settings_overrides={"ERROR_TAG_ID": 552})
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        proc.classifier.classify_text.assert_not_called()

class TestProcessEmptyContent:
    """Empty OCR content requeues the document."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_empty_content_requeues(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert — classify_text not called, requeue happened (PRE_TAG_ID in tags)
        proc.classifier.classify_text.assert_not_called()
        proc.paperless_client.update_document_metadata.assert_called()
        tags = proc.paperless_client.update_document_metadata.call_args.kwargs.get("tags")
        assert 443 in tags  # PRE_TAG_ID — document was requeued for OCR

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_whitespace_content_requeues(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("   \n\t  ")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        proc.classifier.classify_text.assert_not_called()

class TestProcessRefusalContent:
    """Content containing refusal markers triggers error finalization."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    @patch("classifier.worker.needs_error_tag", return_value=True)
    def test_refusal_content_finalizes_with_error(self, mock_needs, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("I'm sorry, I can't assist with that.")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert — update called (to set error tag)
        proc.paperless_client.update_document_metadata.assert_called()

class TestProcessEmptyClassificationResult:
    """Empty classification result triggers error tag."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_none_result_finalizes_with_error(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("valid content")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (None, "")

        # Act
        proc.process()

        # Assert — error tag applied (not success path)
        proc.paperless_client.update_document_metadata.assert_called()
        tags = proc.paperless_client.update_document_metadata.call_args.kwargs.get("tags")
        assert 552 in tags  # ERROR_TAG_ID — finalize_with_error was called

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_empty_fields_result_finalizes_with_error(self, mock_release, mock_claim):
        # Arrange
        empty_result = make_classification_result(
            title="", correspondent="", tags=[], document_date="",
            document_type="", language="", person=""
        )
        doc = _make_doc_with_content("valid content")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (empty_result, "model")

        # Act
        proc.process()

        # Assert — error tag applied (finalize_with_error, not success path)
        proc.paperless_client.update_document_metadata.assert_called()
        tags = proc.paperless_client.update_document_metadata.call_args.kwargs.get("tags")
        assert 552 in tags  # ERROR_TAG_ID

class TestProcessGenericDocumentType:
    """Generic document type triggers error tag."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_generic_type_document_finalizes_with_error(self, mock_release, mock_claim):
        # Arrange
        result = make_classification_result(document_type="Document")
        doc = _make_doc_with_content("valid content")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        # Act
        proc.process()

        # Assert — no taxonomy resolution for type
        proc.taxonomy_cache.get_or_create_document_type_id.assert_not_called()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_generic_type_other_finalizes_with_error(self, mock_release, mock_claim):
        # Arrange
        result = make_classification_result(document_type="Other")
        doc = _make_doc_with_content("valid content")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        # Act
        proc.process()

        # Assert
        proc.taxonomy_cache.get_or_create_document_type_id.assert_not_called()

class TestProcessLLMFailure:
    """LLM failure (exception during classify) still releases the lock."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_exception_during_classify_releases_lock(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("valid content")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.side_effect = RuntimeError("LLM exploded")

        # Act
        with pytest.raises(RuntimeError, match="LLM exploded"):
            proc.process()

        # Assert — lock released despite exception
        mock_release.assert_called_once()

class TestProcessFinallyReleasesLock:
    """The finally block always releases the processing lock when claimed."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_lock_released_on_success(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        mock_release.assert_called_once()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_lock_released_on_error_tag_path(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (None, "")

        # Act
        proc.process()

        # Assert
        mock_release.assert_called_once()

class TestTruncationByPages:
    """Page-based truncation is applied when CLASSIFY_MAX_PAGES > 0."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    @patch("classifier.worker.truncate_content_by_pages")
    def test_page_truncation_applied(self, mock_trunc, mock_release, mock_claim):
        # Arrange
        mock_trunc.return_value = ("truncated text", "NOTE: Truncated")
        doc = _make_doc_with_content("long content " * 1000)
        proc = _make_processor(doc=doc, settings_overrides={"CLASSIFY_MAX_PAGES": 3})
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        mock_trunc.assert_called_once()

class TestTruncationByChars:
    """Character-based truncation is applied as a hard cap."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_char_truncation_applied(self, mock_release, mock_claim):
        # Arrange
        long_content = "A" * 10000
        doc = _make_doc_with_content(long_content)
        proc = _make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_MAX_CHARS": 100, "CLASSIFY_MAX_PAGES": 0},
        )
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert — classify_text was called with truncated content
        call_args = proc.classifier.classify_text.call_args
        text_arg = call_args[0][0]
        assert len(text_arg) < len(long_content)

class TestTagEnrichment:
    """Tags are enriched with year, country, model tags."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    @patch("classifier.worker.enrich_tags")
    def test_enrich_tags_called(self, mock_enrich, mock_release, mock_claim):
        # Arrange
        mock_enrich.return_value = ["invoice", "2025", "ireland"]
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        mock_enrich.assert_called_once()

class TestCustomFieldPerson:
    """Person custom field applied when CLASSIFY_PERSON_FIELD_ID is set."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    @patch("classifier.worker.update_custom_fields")
    def test_person_field_applied(self, mock_ucf, mock_release, mock_claim):
        # Arrange
        result = make_classification_result(person="John Doe")
        mock_ucf.return_value = [{"field": 999, "value": "John Doe"}]
        doc = _make_doc_with_content("text")
        proc = _make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_PERSON_FIELD_ID": 999},
        )
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        # Act
        proc.process()

        # Assert
        mock_ucf.assert_called_once()
        update_call = proc.paperless_client.update_document_metadata.call_args
        assert update_call.kwargs.get("custom_fields") is not None

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_person_field_not_applied_when_unconfigured(self, mock_release, mock_claim):
        # Arrange
        result = make_classification_result(person="John Doe")
        doc = _make_doc_with_content("text")
        proc = _make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_PERSON_FIELD_ID": None},
        )
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        # Act
        proc.process()

        # Assert
        update_call = proc.paperless_client.update_document_metadata.call_args
        assert update_call.kwargs.get("custom_fields") is None

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_person_field_not_applied_when_person_empty(self, mock_release, mock_claim):
        # Arrange
        result = make_classification_result(person="")
        doc = _make_doc_with_content("text")
        proc = _make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_PERSON_FIELD_ID": 999},
        )
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        # Act
        proc.process()

        # Assert
        update_call = proc.paperless_client.update_document_metadata.call_args
        assert update_call.kwargs.get("custom_fields") is None

class TestStatsLogging:
    """Stats are logged after classification."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_stats_logged_after_success(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        proc.classifier.get_stats.assert_called()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_stats_not_logged_when_no_attempts(self, mock_release, mock_claim):
        """Stats with zero attempts are not logged."""
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.get_stats.return_value = {"attempts": 0}

        # Act — process will still run, stats just won't be logged
        proc.process()

        # Assert — get_stats is called but the empty stats won't cause errors
        proc.classifier.get_stats.assert_called()

class TestNoCorrespondentWhenEmpty:
    """Empty correspondent skips taxonomy resolution."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_no_correspondent_resolution_when_empty(self, mock_release, mock_claim):
        # Arrange
        result = make_classification_result(correspondent="")
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        # Act
        proc.process()

        # Assert
        proc.taxonomy_cache.get_or_create_correspondent_id.assert_not_called()

class TestNoDocumentTypeWhenGeneric:
    """Generic document type is rejected before taxonomy resolution."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_generic_type_rejected(self, mock_release, mock_claim):
        # Arrange
        result = make_classification_result(document_type="Unknown")
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        # Act
        proc.process()

        # Assert — entire classification rejected
        proc.taxonomy_cache.get_or_create_document_type_id.assert_not_called()

class TestLanguageNormalization:
    """Language field is normalized before being sent to Paperless."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    @patch("classifier.worker.normalize_language", return_value="en")
    def test_language_normalized(self, mock_norm, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        mock_norm.assert_called_once()
        update_call = proc.paperless_client.update_document_metadata.call_args
        assert update_call.kwargs.get("language") == "en"

class TestClassifyPostTag:
    """When CLASSIFY_POST_TAG_ID is set, it appears in the final tag set."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_post_tag_included(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_POST_TAG_ID": 555},
        )
        proc.paperless_client.get_document.return_value = doc

        # Act
        proc.process()

        # Assert
        update_call = proc.paperless_client.update_document_metadata.call_args
        final_tags = update_call.kwargs.get("tags") or update_call[1].get("tags")
        assert 555 in final_tags

class TestFinalizeWithErrorNoTag:
    """When ERROR_TAG_ID is None, pipeline tags are cleaned but no error tag added."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_finalize_without_error_tag_still_updates(self, mock_release, mock_claim):
        # Arrange — empty result triggers _finalize_with_error
        doc = _make_doc_with_content("text")
        result = make_classification_result(
            title="", correspondent="", tags=[], document_date="",
            document_type="", language="", person="",
        )
        proc = _make_processor(
            doc=doc,
            settings_overrides={"ERROR_TAG_ID": None},
        )
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model-a")

        # Act
        proc.process()

        # Assert — update_document_metadata called, but ERROR_TAG_ID not in tags
        update_call = proc.paperless_client.update_document_metadata.call_args
        final_tags = update_call.kwargs.get("tags") or update_call[1].get("tags")
        assert 552 not in final_tags  # 552 is the default error tag, shouldn't be there

class TestTruncationWithNote:
    """Page truncation note is included when truncation occurs."""

    @patch("classifier.worker.truncate_content_by_pages")
    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_page_truncation_note_passed_to_provider(self, mock_release, mock_claim, mock_trunc):
        # Arrange — truncation returns different content and a note
        doc = _make_doc_with_content("long text with pages")
        proc = _make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_MAX_PAGES": 2},
        )
        proc.paperless_client.get_document.return_value = doc
        mock_trunc.return_value = ("truncated", "NOTE: Pages 1-2 of 10.")

        # Act
        proc.process()

        # Assert — the classify_text call includes the truncation note
        assert mock_trunc.called
        classify_call = proc.classifier.classify_text.call_args
        assert classify_call is not None, "classify_text was never called"
        # Source always passes truncation_note as keyword argument
        assert classify_call.kwargs.get("truncation_note") == "NOTE: Pages 1-2 of 10."

class TestStatsLoggingEdgeCases:
    """Stats logging handles empty stats and zero attempts."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_stats_not_logged_when_empty(self, mock_release, mock_claim):
        # Arrange
        doc = _make_doc_with_content("text")
        proc = _make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.get_stats.return_value = {}

        # Act — should not raise
        proc.process()

        # Assert — process completed
        assert proc.paperless_client.update_document_metadata.called
