"""Tests for classifier.worker content truncation, tags and metadata fields."""

from __future__ import annotations

from unittest.mock import patch

import pytest

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


class TestBornDigitalTag:
    """Only the OCR gate sets the born-digital tag; the LLM's pick is dropped."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_llm_suggestion_dropped_before_tag_limit(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        result = make_classification_result(tags=("Born-Digital", "legal"))
        proc = make_processor(
            doc=doc,
            settings_overrides={
                "OCR_BORN_DIGITAL_TAG_ID": 1080,
                "CLASSIFY_TAG_LIMIT": 1,
            },
        )
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "gpt-5.4-mini")
        proc.taxonomy_cache.tag_name.return_value = "born-digital"

        proc.process()

        proc.taxonomy_cache.tag_name.assert_any_call(1080)
        tag_names = proc.taxonomy_cache.get_or_create_tag_ids.call_args[0][0]
        assert "legal" in tag_names
        assert "born-digital" not in tag_names

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_existing_tag_kept(self, mock_release, mock_claim):
        doc = make_doc_with_content("text", tags=[443, 1080])
        proc = make_processor(
            doc=doc, settings_overrides={"OCR_BORN_DIGITAL_TAG_ID": 1080}
        )
        proc.paperless_client.get_document.return_value = doc
        proc.taxonomy_cache.tag_name.return_value = "born-digital"

        proc.process()

        update_call = proc.paperless_client.update_document_metadata.call_args
        assert 1080 in update_call.kwargs["tags"]


class TestPipelineTagsNeverAdded:
    """Resolved tags never add a pipeline or born-digital tag to the document."""

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_pipeline_tag_ids_stripped_from_resolved_tags(
        self, mock_release, mock_claim
    ):
        doc = make_doc_with_content("text\n\nTranscribed by model: gpt-5.4-mini")
        proc = make_processor(
            doc=doc,
            settings_overrides={"CLASSIFY_POST_TAG_ID": 555},
        )
        proc.paperless_client.get_document.return_value = doc
        proc.taxonomy_cache.get_or_create_tag_ids.return_value = [301, 443, 444, 552]

        proc.process()

        final_tags = proc.paperless_client.update_document_metadata.call_args.kwargs[
            "tags"
        ]
        assert final_tags == {301, 555}

    @pytest.mark.parametrize(
        "setting",
        ["ERROR_TAG_ID", "OCR_PROCESSING_TAG_ID", "CLASSIFY_PROCESSING_TAG_ID"],
    )
    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_error_and_processing_tag_ids_not_added(
        self, mock_release, mock_claim, setting
    ):
        doc = make_doc_with_content("text\n\nTranscribed by model: gpt-5.4-mini")
        proc = make_processor(doc=doc, settings_overrides={setting: 900})
        proc.paperless_client.get_document.return_value = doc
        proc.taxonomy_cache.get_or_create_tag_ids.return_value = [301, 900]

        proc.process()

        final_tags = proc.paperless_client.update_document_metadata.call_args.kwargs[
            "tags"
        ]
        assert 900 not in final_tags
        assert 301 in final_tags

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_pipeline_tag_name_dropped_before_tag_limit(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        result = make_classification_result(tags=("Classify-Queue", "legal"))
        proc = make_processor(doc=doc, settings_overrides={"CLASSIFY_TAG_LIMIT": 1})
        proc.paperless_client.get_document.return_value = doc
        proc.classifier.classify_text.return_value = (result, "gpt-5.4-mini")
        proc.taxonomy_cache.tag_name.side_effect = {444: "classify-queue"}.get

        proc.process()

        tag_names = proc.taxonomy_cache.get_or_create_tag_ids.call_args[0][0]
        assert "legal" in tag_names
        assert "classify-queue" not in tag_names

    @patch("classifier.worker.claim_processing_tag", return_value=True)
    @patch("classifier.worker.release_processing_tag")
    def test_born_digital_tag_id_not_added(self, mock_release, mock_claim):
        doc = make_doc_with_content("text")
        proc = make_processor(
            doc=doc, settings_overrides={"OCR_BORN_DIGITAL_TAG_ID": 1080}
        )
        proc.paperless_client.get_document.return_value = doc
        proc.taxonomy_cache.tag_name.return_value = "born-digital"
        proc.taxonomy_cache.get_or_create_tag_ids.return_value = [301, 1080]

        proc.process()

        final_tags = proc.paperless_client.update_document_metadata.call_args.kwargs[
            "tags"
        ]
        assert 1080 not in final_tags
        assert 301 in final_tags
