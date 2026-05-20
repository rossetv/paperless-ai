"""Tests for classifier.worker — the ``ClassificationProcessor.process()`` lifecycle.

The content-truncation, tag-enrichment, custom-field, and stats helpers are
covered in ``test_worker_metadata``; this file is split off it for the
500-line ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.helpers.factories import make_classification_result
from tests.unit.classifier.conftest import make_doc_with_content, make_processor


class TestProcessHappyPath:

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_applies_metadata(self, mock_release, mock_claim):
        doc = make_doc_with_content("Invoice from Acme Corp. Total: $100.")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        proc.paperless_client.update_document_metadata.assert_called()
        update_call = proc.paperless_client.update_document_metadata.call_args
        assert update_call.kwargs.get("title") or update_call[1].get("title")

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_resolves_correspondent(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        proc.taxonomy_cache.get_or_create_correspondent_id.assert_called_once_with("Acme Corp")

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_resolves_document_type(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        proc.taxonomy_cache.get_or_create_document_type_id.assert_called_once_with("Invoice")

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_resolves_tags(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        proc.taxonomy_cache.get_or_create_tag_ids.assert_called_once()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_skips_correspondent_resolution_when_empty(self, mock_release, mock_claim):
        result = make_classification_result(correspondent="")
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        proc.process()

        proc.taxonomy_cache.get_or_create_correspondent_id.assert_not_called()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    @patch("classifier.worker.normalise_language", return_value="en")
    def test_normalises_language(self, mock_norm, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        mock_norm.assert_called_once()
        update_call = proc.paperless_client.update_document_metadata.call_args
        assert update_call.kwargs.get("language") == "en"

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_includes_post_tag(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_POST_TAG_ID": 555},
        )
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        update_call = proc.paperless_client.update_document_metadata.call_args
        final_tags = update_call.kwargs.get("tags") or update_call[1].get("tags")
        assert 555 in final_tags


class TestProcessEarlyExits:
    """Conditions that cause process() to exit before LLM classification."""

    @patch("classifier.worker.claim_processing_tag", return_value=False)
    @patch("classifier.worker.release_processing_tag")
    def test_claim_failure_skips_classification(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        proc.classifier.classify_text.assert_not_called()

    @patch("classifier.worker.claim_processing_tag", return_value=False)
    @patch("classifier.worker.release_processing_tag")
    def test_claim_failure_does_not_release_tag(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        mock_release.assert_not_called()

    @patch("classifier.worker.release_processing_tag")
    def test_skips_when_error_tag_present(self, mock_release):
        doc = make_doc_with_content("text", tags=[443, 552])
        proc = make_processor(doc=doc, settings_overrides={"ERROR_TAG_ID": 552})
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        proc.classifier.classify_text.assert_not_called()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_empty_content_requeues(self, mock_release, mock_claim):
        doc = make_doc_with_content("")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        proc.classifier.classify_text.assert_not_called()
        proc.paperless_client.update_document_metadata.assert_called()
        tags = proc.paperless_client.update_document_metadata.call_args.kwargs.get("tags")
        assert 443 in tags  # PRE_TAG_ID — document was requeued for OCR

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_whitespace_content_requeues(self, mock_release, mock_claim):
        doc = make_doc_with_content("   \n\t  ")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        proc.classifier.classify_text.assert_not_called()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    @patch("classifier.worker.needs_error_tag", return_value=True)
    def test_refusal_content_finalises_with_error(self, mock_needs, mock_release, mock_claim):
        doc = make_doc_with_content("I'm sorry, I can't assist with that.")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        proc.paperless_client.update_document_metadata.assert_called()


class TestProcessErrorPaths:
    """Error finalisation triggered by empty/generic classification results."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_none_result_finalises_with_error(self, mock_release, mock_claim):
        doc = make_doc_with_content("valid content")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (None, "")

        proc.process()

        proc.paperless_client.update_document_metadata.assert_called()
        tags = proc.paperless_client.update_document_metadata.call_args.kwargs.get("tags")
        assert 552 in tags  # ERROR_TAG_ID

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_empty_fields_result_finalises_with_error(self, mock_release, mock_claim):
        empty_result = make_classification_result(
            title="", correspondent="", tags=[], document_date="",
            document_type="", language="", person=""
        )
        doc = make_doc_with_content("valid content")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (empty_result, "model")

        proc.process()

        proc.paperless_client.update_document_metadata.assert_called()
        tags = proc.paperless_client.update_document_metadata.call_args.kwargs.get("tags")
        assert 552 in tags  # ERROR_TAG_ID

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_generic_type_document_rejected(self, mock_release, mock_claim):
        result = make_classification_result(document_type="Document")
        doc = make_doc_with_content("valid content")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        proc.process()

        proc.taxonomy_cache.get_or_create_document_type_id.assert_not_called()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_generic_type_other_rejected(self, mock_release, mock_claim):
        result = make_classification_result(document_type="Other")
        doc = make_doc_with_content("valid content")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        proc.process()

        proc.taxonomy_cache.get_or_create_document_type_id.assert_not_called()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_generic_type_unknown_rejected(self, mock_release, mock_claim):
        result = make_classification_result(document_type="Unknown")
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        proc.process()

        proc.taxonomy_cache.get_or_create_document_type_id.assert_not_called()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_finalise_without_error_tag_still_updates(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        result = make_classification_result(
            title="", correspondent="", tags=[], document_date="",
            document_type="", language="", person="",
        )
        proc = make_processor(
            doc=doc,
            settings_overrides={"ERROR_TAG_ID": None},
        )
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model-a")

        proc.process()

        update_call = proc.paperless_client.update_document_metadata.call_args
        final_tags = update_call.kwargs.get("tags") or update_call[1].get("tags")
        assert 552 not in final_tags


class TestProcessLockRelease:
    """The finally block releases the processing lock when claimed."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_lock_released_on_success(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        mock_release.assert_called_once()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_lock_released_on_error_tag_path(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (None, "")

        proc.process()

        mock_release.assert_called_once()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_lock_released_on_llm_exception(self, mock_release, mock_claim):
        doc = make_doc_with_content("valid content")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.side_effect = RuntimeError("LLM exploded")

        with pytest.raises(RuntimeError, match="LLM exploded"):
            proc.process()

        mock_release.assert_called_once()
