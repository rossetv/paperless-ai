"""Tests for end-to-end OCR workflow."""

from __future__ import annotations

import io
from unittest.mock import MagicMock

from PIL import Image

from ocr.worker import OcrProcessor
from ocr.text_assembly import OCR_ERROR_MARKER
from tests.helpers.factories import make_document, make_png_bytes, make_settings_obj


def _make_settings(**overrides):
    """Create a settings mock suitable for OCR e2e tests."""
    defaults = {
        "OCR_PROCESSING_TAG_ID": 500,
        "PRE_TAG_ID": 443,
        "POST_TAG_ID": 444,
        "ERROR_TAG_ID": 552,
        "REFUSAL_MARK": "CHATGPT REFUSED TO TRANSCRIBE",
        "OCR_DPI": 72,
        "OCR_MAX_SIDE": 200,
        "PAGE_WORKERS": 1,
        "OCR_INCLUDE_PAGE_MODELS": False,
        "CLASSIFY_PRE_TAG_ID": 444,
        "CLASSIFY_POST_TAG_ID": None,
        "CLASSIFY_PROCESSING_TAG_ID": None,
    }
    defaults.update(overrides)
    return make_settings_obj(**defaults)


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
    # Mutable state: current tags for the document
    state = {"tags": list(initial_doc.get("tags", []))}

    def get_document(doc_id):
        doc_copy = dict(initial_doc)
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
    client.download_content.return_value = (b"fake", "application/pdf")
    return client, state


def _make_mock_ocr_provider(transcribe_return=None, transcribe_side_effect=None):
    """Create a mock OCR provider."""
    provider = MagicMock()
    if transcribe_side_effect is not None:
        provider.transcribe_image.side_effect = transcribe_side_effect
    elif transcribe_return is not None:
        provider.transcribe_image.return_value = transcribe_return
    else:
        provider.transcribe_image.return_value = (
            "This is the transcribed text of the document.", "gpt-5.4-mini"
        )
    provider.get_stats.return_value = {
        "attempts": 1,
        "refusals": 0,
        "api_errors": 0,
        "fallback_successes": 0,
    }
    return provider

class TestOcrHappyPath:
    """Complete happy path: download -> convert -> OCR -> update Paperless."""

    def test_complete_ocr_workflow(self):
        """
        Full OCR lifecycle:
        1. Create a OcrProcessor with mocks
        2. download_content returns real PNG image bytes
        3. get_document returns document with pre-tag
        4. Run process()
        5. Verify update_document called with correct text and tags
        6. Verify processing tag released
        """
        settings = _make_settings()
        png_bytes = make_png_bytes()

        doc = make_document(id=42, tags=[443], title="Test PDF")
        client, state = _make_stateful_client(doc)
        client.download_content.return_value = (png_bytes, "image/png")

        provider = _make_mock_ocr_provider(
            transcribe_return=("Invoice from Acme Corp. Total: $500.", "gpt-5.4-mini")
        )

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        # Verify OCR provider was called
        provider.transcribe_image.assert_called_once()

        # Verify update_document was called
        client.update_document.assert_called_once()
        call_args = client.update_document.call_args
        doc_id = call_args[0][0]
        content = call_args[0][1]
        tags = call_args[0][2]

        assert doc_id == 42
        assert "Invoice from Acme Corp" in content
        assert "Transcribed by model: gpt-5.4-mini" in content
        # POST_TAG_ID should be added, PRE_TAG_ID removed
        assert 444 in tags  # POST_TAG_ID
        assert 443 not in tags  # PRE_TAG_ID removed

        # The processing tag (500) should be absent from the final state.
        # Note: the happy path in _update_paperless_document already discards
        # the processing tag before calling update_document, and then
        # release_processing_tag in the finally block confirms it's gone.
        assert 500 not in state["tags"]
        assert 500 not in tags  # also absent from the update_document call itself

    def test_multi_page_ocr_workflow(self):
        """Multi-frame TIFF produces multi-page text with page headers."""
        settings = _make_settings()

        # Create a multi-frame TIFF
        frames = [
            Image.new("RGB", (10, 10), color="red"),
            Image.new("RGB", (10, 10), color="green"),
        ]
        buf = io.BytesIO()
        frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:])
        tiff_bytes = buf.getvalue()

        doc = make_document(id=10, tags=[443])
        client, state = _make_stateful_client(doc)
        client.download_content.return_value = (tiff_bytes, "image/tiff")

        call_count = [0]

        def transcribe_side_effect(image, doc_id=None, page_num=None):
            call_count[0] += 1
            return (f"Content of page {page_num}.", "gpt-5.4-mini")

        provider = _make_mock_ocr_provider(
            transcribe_side_effect=transcribe_side_effect
        )

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        # Both pages transcribed
        assert call_count[0] == 2

        # Verify assembled text has page headers
        content = client.update_document.call_args[0][1]
        assert "--- Page 1 ---" in content
        assert "--- Page 2 ---" in content

class TestOcrErrorPath:
    """OCR provider fails, document gets error tag."""

    def test_provider_raises_for_all_images(self):
        """
        When the OCR provider raises exceptions for all images:
        1. process() handles the error
        2. Error tag is added
        3. Processing tag is released
        """
        settings = _make_settings()
        png_bytes = make_png_bytes()

        doc = make_document(id=42, tags=[443])
        client, state = _make_stateful_client(doc)
        client.download_content.return_value = (png_bytes, "image/png")

        # Provider raises for every call
        provider = _make_mock_ocr_provider(
            transcribe_side_effect=Exception("Model unavailable")
        )

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        # The OCR error marker is in the assembled text, triggering error handling.
        # update_document should be called with error-marked content and error tag.
        assert client.update_document.called
        content = client.update_document.call_args[0][1]
        tags = client.update_document.call_args[0][2]
        assert OCR_ERROR_MARKER in content
        assert 552 in tags  # ERROR_TAG_ID

    def test_refusal_mark_triggers_error(self):
        """When provider returns refusal mark, document gets error tag."""
        settings = _make_settings()
        png_bytes = make_png_bytes()

        doc = make_document(id=42, tags=[443])
        client, state = _make_stateful_client(doc)
        client.download_content.return_value = (png_bytes, "image/png")

        provider = _make_mock_ocr_provider(
            transcribe_return=("CHATGPT REFUSED TO TRANSCRIBE", "")
        )

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        # Error path: update_document called with error tag
        assert client.update_document.called
        tags = client.update_document.call_args[0][2]
        assert 552 in tags  # ERROR_TAG_ID

    def test_corrupt_image_triggers_error(self):
        """Corrupt image bytes triggers error handling."""
        settings = _make_settings()

        doc = make_document(id=42, tags=[443])
        client, state = _make_stateful_client(doc)
        # Return corrupt bytes that will fail image conversion
        client.download_content.return_value = (b"not-an-image", "image/png")

        provider = _make_mock_ocr_provider()

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        # Provider should NOT have been called (conversion fails first)
        provider.transcribe_image.assert_not_called()

        # Error tag should be applied via update_document_metadata
        # The _finalize_with_error path calls update_document_metadata with error tag
        assert 552 in state["tags"]

class TestOcrLockContention:
    """Document already has processing tag -- claim fails, early exit."""

    def test_already_claimed_document_skipped(self):
        """
        When the document already has the processing tag:
        1. claim fails
        2. No update_document call
        3. Early exit
        """
        settings = _make_settings()

        # Document already has the processing tag (500)
        doc = make_document(id=42, tags=[443, 500])
        client, state = _make_stateful_client(doc)

        provider = _make_mock_ocr_provider()

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        # No OCR was attempted
        provider.transcribe_image.assert_not_called()
        # No content update was made
        client.update_document.assert_not_called()
        # download_content should not have been called
        client.download_content.assert_not_called()

    def test_no_processing_tag_configured_always_proceeds(self):
        """When OCR_PROCESSING_TAG_ID is None, claim always succeeds."""
        settings = _make_settings(OCR_PROCESSING_TAG_ID=None)
        png_bytes = make_png_bytes()

        doc = make_document(id=42, tags=[443])
        client, state = _make_stateful_client(doc)
        client.download_content.return_value = (png_bytes, "image/png")

        provider = _make_mock_ocr_provider(
            transcribe_return=("Transcribed text.", "gpt-5.4-mini")
        )

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        # OCR was performed
        provider.transcribe_image.assert_called_once()
        # Document was updated
        client.update_document.assert_called_once()

    def test_error_tag_skips_processing(self):
        """Document with error tag is skipped."""
        settings = _make_settings()

        doc = make_document(id=42, tags=[443, 552])  # has error tag
        client, state = _make_stateful_client(doc)

        provider = _make_mock_ocr_provider()

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        # No OCR attempted
        provider.transcribe_image.assert_not_called()
        # No content update
        client.update_document.assert_not_called()
