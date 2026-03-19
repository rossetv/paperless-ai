"""Tests for end-to-end classifier workflow."""

from __future__ import annotations

from unittest.mock import MagicMock

from classifier.taxonomy import TaxonomyCache
from classifier.worker import ClassificationProcessor
from tests.helpers.factories import (
    make_classification_result,
    make_document,
    make_settings_obj,
)

def _make_settings(**overrides):
    """Create a settings mock suitable for classification e2e tests."""
    defaults = {
        "CLASSIFY_PROCESSING_TAG_ID": 600,
        "CLASSIFY_PRE_TAG_ID": 444,
        "CLASSIFY_POST_TAG_ID": 555,
        "PRE_TAG_ID": 443,
        "POST_TAG_ID": 444,
        "ERROR_TAG_ID": 552,
        "OCR_PROCESSING_TAG_ID": None,
        "CLASSIFY_MAX_PAGES": 3,
        "CLASSIFY_TAIL_PAGES": 2,
        "CLASSIFY_HEADERLESS_CHAR_LIMIT": 15000,
        "CLASSIFY_MAX_CHARS": 0,
        "CLASSIFY_TAG_LIMIT": 5,
        "CLASSIFY_DEFAULT_COUNTRY_TAG": "DE",
        "CLASSIFY_TAXONOMY_LIMIT": 100,
        "CLASSIFY_PERSON_FIELD_ID": 7,
        "CLASSIFY_MAX_TOKENS": 0,
        "LLM_PROVIDER": "openai",
        "REQUEST_TIMEOUT": 180,
        "AI_MODELS": ["gpt-5-mini"],
        "REFUSAL_MARK": "CHATGPT REFUSED TO TRANSCRIBE",
    }
    defaults.update(overrides)
    return make_settings_obj(**defaults)


def _make_ocr_content(num_pages: int = 3, model: str = "gpt-5-mini") -> str:
    """Build realistic OCR content with page headers and model footer."""
    pages = []
    for i in range(1, num_pages + 1):
        pages.append(f"--- Page {i} ---")
        pages.append(
            f"This is the content of page {i}. "
            "It contains important information about an invoice from Acme Corp. "
            f"The total amount is ${i * 100}.00."
        )
    body = "\n\n".join(pages)
    footer = f"\n\nTranscribed by model: {model}"
    return body + footer


def _make_stateful_client(initial_doc):
    """
    Create a mock PaperlessClient that tracks tag state across calls.

    The claim_processing_tag workflow does:
      1. get_document (refresh) -> check tag absent
      2. update_document_metadata (add tag)
      3. get_document (verify) -> check tag present

    This mock tracks tags so the verify step succeeds.
    """
    client = MagicMock()
    state = {"tags": list(initial_doc.get("tags", [])), "doc": dict(initial_doc)}

    def get_document(doc_id):
        doc_copy = dict(state["doc"])
        doc_copy["tags"] = list(state["tags"])
        return doc_copy

    def update_document_metadata(doc_id, **kwargs):
        if "tags" in kwargs:
            state["tags"] = list(kwargs["tags"])

    def update_document(doc_id, content, tags):
        state["tags"] = list(tags)

    client.get_document.side_effect = get_document
    client.update_document_metadata.side_effect = update_document_metadata
    client.update_document.side_effect = update_document

    # Taxonomy API stubs
    client.list_correspondents.return_value = [
        {"id": 1, "name": "Acme Corp", "document_count": 10, "matching_algorithm": "none"},
    ]
    client.list_document_types.return_value = [
        {"id": 10, "name": "Invoice", "document_count": 20, "matching_algorithm": "none"},
        {"id": 11, "name": "Receipt", "document_count": 5, "matching_algorithm": "none"},
    ]
    client.list_tags.return_value = [
        {"id": 100, "name": "2025", "matching_algorithm": "none", "document_count": 30},
        {"id": 101, "name": "invoice", "matching_algorithm": "none", "document_count": 15},
        {"id": 102, "name": "payment", "matching_algorithm": "none", "document_count": 8},
        {"id": 103, "name": "de", "matching_algorithm": "none", "document_count": 25},
    ]

    _next_id = [200]

    def _create_tag(name, **kw):
        tag_id = _next_id[0]
        _next_id[0] += 1
        return {"id": tag_id, "name": name, "matching_algorithm": "none"}

    client.create_tag.side_effect = _create_tag
    client.create_correspondent.side_effect = lambda name, **kw: {"id": 300, "name": name}
    client.create_document_type.side_effect = lambda name, **kw: {"id": 301, "name": name}

    return client, state


def _make_taxonomy_cache(client):
    """Create and refresh a TaxonomyCache from a mock client."""
    cache = TaxonomyCache(client, taxonomy_limit=100)
    cache.refresh()
    return cache


def _make_mock_classifier(result=None, model="gpt-5-mini"):
    """Create a mock ClassificationProvider."""
    mock = MagicMock()
    if result is None:
        result = make_classification_result(
            title="Invoice from Acme Corp",
            correspondent="Acme Corp",
            tags=["invoice", "payment"],
            document_date="2025-06-15",
            document_type="Invoice",
            language="en",
            person="John Doe",
        )
    mock.classify_text.return_value = (result, model)
    mock.get_stats.return_value = {
        "attempts": 1,
        "api_errors": 0,
        "invalid_json": 0,
        "fallback_successes": 0,
    }
    return mock

class TestClassifierHappyPath:
    """Complete classification lifecycle with realistic data."""

    def test_complete_classification_workflow(self):
        """
        Full classification lifecycle:
        1. Create ClassificationProcessor with mocks
        2. Document has OCR content with page headers and model footer
        3. Mock provider returns valid ClassificationResult
        4. Taxonomy cache pre-populated with items
        5. Run process()
        6. Verify update_document_metadata called with correct fields
        7. Verify processing tag released
        """
        settings = _make_settings()
        ocr_content = _make_ocr_content(num_pages=3)

        doc = make_document(
            id=42,
            tags=[444],  # CLASSIFY_PRE_TAG_ID
            content=ocr_content,
            title="Scanned Document",
            created="2025-01-15",
        )

        client, state = _make_stateful_client(doc)
        classifier = _make_mock_classifier()
        taxonomy_cache = _make_taxonomy_cache(client)

        processor = ClassificationProcessor(
            doc=doc,
            paperless_client=client,
            classifier=classifier,
            taxonomy_cache=taxonomy_cache,
            settings=settings,
        )
        processor.process()

        # Verify classifier was called
        classifier.classify_text.assert_called_once()

        # Verify the final tag state includes expected items
        final_tags = set(state["tags"])

        # CLASSIFY_POST_TAG_ID should be present
        assert 555 in final_tags

        # Processing tag (600) should be released
        assert 600 not in final_tags

        # Find the classification update call (the one with title)
        classification_call = None
        for c in client.update_document_metadata.call_args_list:
            kwargs = c[1] if c[1] else {}
            if "title" in kwargs:
                classification_call = c
                break

        assert classification_call is not None, (
            "Expected update_document_metadata call with classification fields"
        )
        kwargs = classification_call[1]

        # Verify title
        assert kwargs.get("title") == "Invoice from Acme Corp"

        # Verify correspondent_id (Acme Corp exists with id=1)
        assert kwargs.get("correspondent_id") == 1

        # Verify document_type_id (Invoice exists with id=10)
        assert kwargs.get("document_type_id") == 10

        # Verify date
        assert kwargs.get("document_date") == "2025-06-15"

        # Verify language
        assert kwargs.get("language") == "en"

        # Verify custom fields (person field)
        custom_fields = kwargs.get("custom_fields")
        assert custom_fields is not None
        person_field = next(
            (f for f in custom_fields if f["field"] == 7), None
        )
        assert person_field is not None
        assert person_field["value"] == "John Doe"

    def test_classification_with_new_correspondent(self):
        """New correspondent triggers creation via taxonomy cache."""
        settings = _make_settings()
        ocr_content = _make_ocr_content()

        doc = make_document(id=42, tags=[444], content=ocr_content)
        client, state = _make_stateful_client(doc)

        result = make_classification_result(
            correspondent="Brand New Company",
            document_type="Invoice",
        )
        classifier = _make_mock_classifier(result=result)
        taxonomy_cache = _make_taxonomy_cache(client)

        processor = ClassificationProcessor(
            doc=doc,
            paperless_client=client,
            classifier=classifier,
            taxonomy_cache=taxonomy_cache,
            settings=settings,
        )
        processor.process()

        # New correspondent should be created
        client.create_correspondent.assert_called_once_with("Brand New Company")

    def test_classification_without_person_field(self):
        """When person is empty, custom_fields is not set."""
        settings = _make_settings()
        ocr_content = _make_ocr_content()

        doc = make_document(id=42, tags=[444], content=ocr_content)
        client, state = _make_stateful_client(doc)

        result = make_classification_result(person="")
        classifier = _make_mock_classifier(result=result)
        taxonomy_cache = _make_taxonomy_cache(client)

        processor = ClassificationProcessor(
            doc=doc,
            paperless_client=client,
            classifier=classifier,
            taxonomy_cache=taxonomy_cache,
            settings=settings,
        )
        processor.process()

        # Find the classification update call
        classification_call = None
        for c in client.update_document_metadata.call_args_list:
            kwargs = c[1] if c[1] else {}
            if "title" in kwargs:
                classification_call = c
                break

        assert classification_call is not None, "update_document_metadata was never called with 'title'"
        kwargs = classification_call[1]
        # custom_fields should be None (no person to set)
        assert kwargs.get("custom_fields") is None

class TestClassifierEmptyContent:
    """Document has empty or blank content."""

    def test_empty_content_requeues_for_ocr(self):
        """
        Document with empty content:
        1. Run process()
        2. Verify requeue (PRE_TAG_ID added back)
        """
        settings = _make_settings()

        doc = make_document(id=42, tags=[444], content="")
        client, state = _make_stateful_client(doc)

        classifier = _make_mock_classifier()
        taxonomy_cache = _make_taxonomy_cache(client)

        processor = ClassificationProcessor(
            doc=doc,
            paperless_client=client,
            classifier=classifier,
            taxonomy_cache=taxonomy_cache,
            settings=settings,
        )
        processor.process()

        # Classifier should not have been called
        classifier.classify_text.assert_not_called()

        # Document should be requeued: PRE_TAG_ID in final tags
        assert 443 in state["tags"]

    def test_whitespace_only_content_requeues(self):
        """Whitespace-only content is treated as empty."""
        settings = _make_settings()

        doc = make_document(id=42, tags=[444], content="   \n\n   ")
        client, state = _make_stateful_client(doc)

        classifier = _make_mock_classifier()
        taxonomy_cache = _make_taxonomy_cache(client)

        processor = ClassificationProcessor(
            doc=doc,
            paperless_client=client,
            classifier=classifier,
            taxonomy_cache=taxonomy_cache,
            settings=settings,
        )
        processor.process()

        classifier.classify_text.assert_not_called()

class TestClassifierRefusalContent:
    """Document content contains refusal markers."""

    def test_refusal_content_gets_error_tag(self):
        """
        When document content contains refusal markers:
        1. Run process()
        2. Verify error tag applied
        """
        settings = _make_settings()

        # Content with a refusal phrase
        refusal_content = (
            "--- Page 1 ---\n"
            "I'm sorry, I can't assist with that.\n\n"
            "Transcribed by model: gpt-5-mini"
        )

        doc = make_document(id=42, tags=[444], content=refusal_content)
        client, state = _make_stateful_client(doc)

        # The classifier will be called (content is not empty), and might
        # return a valid result, but _apply_classification checks for
        # needs_error_tag on the original content.
        classifier = _make_mock_classifier()
        taxonomy_cache = _make_taxonomy_cache(client)

        processor = ClassificationProcessor(
            doc=doc,
            paperless_client=client,
            classifier=classifier,
            taxonomy_cache=taxonomy_cache,
            settings=settings,
        )
        processor.process()

        # Error tag should be in final state
        assert 552 in state["tags"]

    def test_redacted_marker_content_gets_error_tag(self):
        """Content with [REDACTED] markers triggers error."""
        settings = _make_settings()

        redacted_content = (
            "--- Page 1 ---\n"
            "Dear [REDACTED NAME],\n"
            "Your account [REDACTED] has been updated.\n\n"
            "Transcribed by model: gpt-5-mini"
        )

        doc = make_document(id=42, tags=[444], content=redacted_content)
        client, state = _make_stateful_client(doc)

        classifier = _make_mock_classifier()
        taxonomy_cache = _make_taxonomy_cache(client)

        processor = ClassificationProcessor(
            doc=doc,
            paperless_client=client,
            classifier=classifier,
            taxonomy_cache=taxonomy_cache,
            settings=settings,
        )
        processor.process()

        # Error tag should be in final state
        assert 552 in state["tags"]

    def test_generic_document_type_gets_error_tag(self):
        """Classification returning a generic document type triggers error."""
        settings = _make_settings()
        ocr_content = _make_ocr_content()

        doc = make_document(id=42, tags=[444], content=ocr_content)
        client, state = _make_stateful_client(doc)

        # Return a result with a generic document type
        result = make_classification_result(document_type="Document")
        classifier = _make_mock_classifier(result=result)
        taxonomy_cache = _make_taxonomy_cache(client)

        processor = ClassificationProcessor(
            doc=doc,
            paperless_client=client,
            classifier=classifier,
            taxonomy_cache=taxonomy_cache,
            settings=settings,
        )
        processor.process()

        # Error tag should be in final state
        assert 552 in state["tags"]

    def test_classifier_returns_none_gets_error_tag(self):
        """When classifier returns None result, error tag is applied."""
        settings = _make_settings()
        ocr_content = _make_ocr_content()

        doc = make_document(id=42, tags=[444], content=ocr_content)
        client, state = _make_stateful_client(doc)

        classifier = MagicMock()
        classifier.classify_text.return_value = (None, "")
        classifier.get_stats.return_value = {"attempts": 1}
        taxonomy_cache = _make_taxonomy_cache(client)

        processor = ClassificationProcessor(
            doc=doc,
            paperless_client=client,
            classifier=classifier,
            taxonomy_cache=taxonomy_cache,
            settings=settings,
        )
        processor.process()

        # Error tag should be in final state
        assert 552 in state["tags"]

    def test_already_claimed_document_skipped(self):
        """Document with processing tag is skipped (claim fails)."""
        settings = _make_settings()

        doc = make_document(id=42, tags=[444, 600], content=_make_ocr_content())
        client, state = _make_stateful_client(doc)

        classifier = _make_mock_classifier()
        taxonomy_cache = _make_taxonomy_cache(client)

        processor = ClassificationProcessor(
            doc=doc,
            paperless_client=client,
            classifier=classifier,
            taxonomy_cache=taxonomy_cache,
            settings=settings,
        )
        processor.process()

        # Classifier should not have been called
        classifier.classify_text.assert_not_called()
