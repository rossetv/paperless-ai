"""Tests for classifier.worker — content, tag, and metadata application.

Covers content truncation, tag enrichment, the person custom field, and stats
logging.  Split from ``test_worker`` (the ``process()`` lifecycle) for the
500-line ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

from unittest.mock import patch

from tests.helpers.factories import make_classification_result
from tests.unit.classifier.conftest import make_doc_with_content, make_processor


class TestContentTruncation:
    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    @patch("classifier.worker.truncate_content_by_pages")
    def test_page_truncation_applied(self, mock_trunc, mock_release, mock_claim):
        mock_trunc.return_value = ("truncated text", "NOTE: Truncated")
        doc = make_doc_with_content("long content " * 1000)
        proc = make_processor(doc=doc, settings_overrides={"CLASSIFY_MAX_PAGES": 3})
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        mock_trunc.assert_called_once()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_char_truncation_applied(self, mock_release, mock_claim):
        long_content = "A" * 10000
        doc = make_doc_with_content(long_content)
        proc = make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_MAX_CHARS": 100, "CLASSIFY_MAX_PAGES": 0},
        )
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        call_args = proc.classifier.classify_text.call_args
        text_arg = call_args[0][0]
        assert len(text_arg) < len(long_content)

    @patch("classifier.worker.truncate_content_by_pages")
    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_page_truncation_note_passed_to_provider(
        self, mock_release, mock_claim, mock_trunc
    ):
        doc = make_doc_with_content("long text with pages")
        proc = make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_MAX_PAGES": 2},
        )
        proc.paperless_client.get_document.return_value = doc
        mock_trunc.return_value = ("truncated", "NOTE: Pages 1-2 of 10.")

        proc.process()

        assert mock_trunc.called
        classify_call = proc.classifier.classify_text.call_args
        assert classify_call is not None, "classify_text was never called"
        assert classify_call.kwargs.get("truncation_note") == "NOTE: Pages 1-2 of 10."


class TestTagEnrichment:
    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    @patch("classifier.worker.enrich_tags")
    def test_enrich_tags_called(self, mock_enrich, mock_release, mock_claim):
        mock_enrich.return_value = ["invoice", "2025", "ireland"]
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        mock_enrich.assert_called_once()


class TestCustomFieldPerson:
    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    @patch("classifier.worker.update_custom_fields")
    def test_person_field_applied(self, mock_ucf, mock_release, mock_claim):
        result = make_classification_result(person="John Doe")
        mock_ucf.return_value = [{"field": 999, "value": "John Doe"}]
        doc = make_doc_with_content("text")
        proc = make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_PERSON_FIELD_ID": 999},
        )
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        proc.process()

        mock_ucf.assert_called_once()
        update_call = proc.paperless_client.update_document_metadata.call_args
        assert update_call.kwargs.get("custom_fields") is not None

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_person_field_not_applied_when_unconfigured(self, mock_release, mock_claim):
        result = make_classification_result(person="John Doe")
        doc = make_doc_with_content("text")
        proc = make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_PERSON_FIELD_ID": None},
        )
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        proc.process()

        update_call = proc.paperless_client.update_document_metadata.call_args
        assert update_call.kwargs.get("custom_fields") is None

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_person_field_not_applied_when_person_empty(self, mock_release, mock_claim):
        result = make_classification_result(person="")
        doc = make_doc_with_content("text")
        proc = make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_PERSON_FIELD_ID": 999},
        )
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "model")

        proc.process()

        update_call = proc.paperless_client.update_document_metadata.call_args
        assert update_call.kwargs.get("custom_fields") is None


class TestStatsLogging:
    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_stats_logged_after_success(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc

        proc.process()

        proc.classifier.get_stats.assert_called()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_stats_not_logged_when_no_attempts(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.get_stats.return_value = {"attempts": 0}

        proc.process()

        proc.classifier.get_stats.assert_called()

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_stats_not_logged_when_empty(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(doc=doc)
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.get_stats.return_value = {}

        proc.process()

        assert proc.paperless_client.update_document_metadata.called
