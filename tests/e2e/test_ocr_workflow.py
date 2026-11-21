"""End-to-end tests for the OCR workflow over a stateful Paperless mock."""

from __future__ import annotations

import io
from unittest.mock import patch

from PIL import Image

from ocr.born_digital import BornDigitalDecision
from ocr.text_assembly import OCR_ERROR_MARKER, PageResult
from ocr.worker import OcrProcessor
from tests.helpers.factories import make_document, make_png_bytes, make_settings_obj
from tests.helpers.mocks import make_mock_ocr_provider, make_stateful_paperless


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


class TestOcrHappyPath:
    """Complete happy path: download -> convert -> OCR -> update Paperless."""

    def test_complete_ocr_workflow(self):
        """A PNG is OCR'd and written back with the post-tag; the lock is released."""
        settings = _make_settings()
        png_bytes = make_png_bytes()

        doc = make_document(id=42, tags=[443], title="Test PDF")
        client, state = make_stateful_paperless(doc)
        client.download_content.return_value = (png_bytes, "image/png")

        provider = make_mock_ocr_provider()
        provider.transcribe_image.return_value = PageResult(
            "Invoice from Acme Corp. Total: $500.", "gpt-5.4-mini"
        )

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        provider.transcribe_image.assert_called_once()

        client.update_document.assert_called_once()
        call_args = client.update_document.call_args
        doc_id = call_args[0][0]
        content = call_args[0][1]
        tags = call_args[0][2]

        assert doc_id == 42
        assert "Invoice from Acme Corp" in content
        assert "Transcribed by model: gpt-5.4-mini" in content
        assert 444 in tags  # POST_TAG_ID
        assert 443 not in tags  # PRE_TAG_ID removed

        # The processing tag (500) is dropped before update_document and
        # released again in the finally block.
        assert 500 not in state["tags"]
        assert 500 not in tags  # also absent from the update_document call itself

    def test_multi_page_ocr_workflow(self):
        """Multi-frame TIFF produces multi-page text with page headers."""
        settings = _make_settings()

        frames = [
            Image.new("RGB", (10, 10), color="red"),
            Image.new("RGB", (10, 10), color="green"),
        ]
        buf = io.BytesIO()
        frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:])
        tiff_bytes = buf.getvalue()

        doc = make_document(id=10, tags=[443])
        client, state = make_stateful_paperless(doc)
        client.download_content.return_value = (tiff_bytes, "image/tiff")

        call_count = [0]

        def transcribe_side_effect(image, doc_id=None, page_num=None):
            call_count[0] += 1
            return PageResult(f"Content of page {page_num}.", "gpt-5.4-mini")

        provider = make_mock_ocr_provider()
        provider.transcribe_image.side_effect = transcribe_side_effect

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        assert call_count[0] == 2

        content = client.update_document.call_args[0][1]
        assert "--- Page 1 ---" in content
        assert "--- Page 2 ---" in content


class TestOcrErrorPath:
    """OCR provider fails, document gets error tag."""

    def test_provider_raises_for_all_images(self):
        """When the OCR provider raises for every image, the error tag is applied."""
        settings = _make_settings()
        png_bytes = make_png_bytes()

        doc = make_document(id=42, tags=[443])
        client, state = make_stateful_paperless(doc)
        client.download_content.return_value = (png_bytes, "image/png")

        provider = make_mock_ocr_provider()
        provider.transcribe_image.side_effect = Exception("Model unavailable")

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        # The OCR error marker in the assembled text triggers the error path.
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
        client, state = make_stateful_paperless(doc)
        client.download_content.return_value = (png_bytes, "image/png")

        provider = make_mock_ocr_provider()
        provider.transcribe_image.return_value = PageResult(
            "CHATGPT REFUSED TO TRANSCRIBE", ""
        )

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        assert client.update_document.called
        tags = client.update_document.call_args[0][2]
        assert 552 in tags  # ERROR_TAG_ID

    def test_corrupt_image_triggers_error(self):
        """Corrupt image bytes triggers error handling."""
        settings = _make_settings()

        doc = make_document(id=42, tags=[443])
        client, state = make_stateful_paperless(doc)
        client.download_content.return_value = (b"not-an-image", "image/png")

        provider = make_mock_ocr_provider()

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        # Conversion fails before the provider is reached.
        provider.transcribe_image.assert_not_called()

        # finalise_document_with_error applies the tag via update_document_metadata.
        assert 552 in state["tags"]


class TestOcrLockContention:
    """Document already has processing tag -- claim fails, early exit."""

    def test_already_claimed_document_skipped(self):
        """A document that already has the processing tag is left untouched."""
        settings = _make_settings()

        # Document already has the processing tag (500)
        doc = make_document(id=42, tags=[443, 500])
        client, state = make_stateful_paperless(doc)

        provider = make_mock_ocr_provider()

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        provider.transcribe_image.assert_not_called()
        client.update_document.assert_not_called()
        client.download_content.assert_not_called()

    def test_no_processing_tag_configured_always_proceeds(self):
        """When OCR_PROCESSING_TAG_ID is None, claim always succeeds."""
        settings = _make_settings(OCR_PROCESSING_TAG_ID=None)
        png_bytes = make_png_bytes()

        doc = make_document(id=42, tags=[443])
        client, state = make_stateful_paperless(doc)
        client.download_content.return_value = (png_bytes, "image/png")

        provider = make_mock_ocr_provider()
        provider.transcribe_image.return_value = PageResult(
            "Transcribed text.", "gpt-5.4-mini"
        )

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        provider.transcribe_image.assert_called_once()
        client.update_document.assert_called_once()

    def test_error_tag_skips_processing(self):
        """Document with error tag is skipped."""
        settings = _make_settings()

        doc = make_document(id=42, tags=[443, 552])  # has error tag
        client, state = make_stateful_paperless(doc)

        provider = make_mock_ocr_provider()

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        processor.process()

        provider.transcribe_image.assert_not_called()
        client.update_document.assert_not_called()


class TestOcrBornDigitalSkip:
    """The poppler gate skips a born-digital PDF before any vision OCR."""

    def test_e2e_born_digital_skips_and_advances_tag(self):
        """A skipped PDF gets no OCR or content write; PRE becomes POST plus marker.

        The poppler gate is mocked at the ``classify_original`` seam.
        """
        doc = make_document(
            mime_type="application/pdf",
            content="real born-digital text " * 40,
            tags=[443],
        )
        client, state = make_stateful_paperless(doc)
        client.download_original.return_value = (b"%PDF", "application/pdf")

        settings = make_settings_obj(
            OCR_SKIP_BORN_DIGITAL=True,
            PRE_TAG_ID=443,
            POST_TAG_ID=444,
            OCR_BORN_DIGITAL_TAG_ID=555,
        )
        provider = make_mock_ocr_provider()

        processor = OcrProcessor(
            doc=doc,
            paperless_client=client,
            ocr_provider=provider,
            settings=settings,
        )
        with patch(
            "ocr.worker.classify_original",
            return_value=BornDigitalDecision(True, "born-digital", {}),
        ):
            outcome = processor.process()

        assert outcome is None
        assert 444 in state["tags"] and 443 not in state["tags"]  # PRE -> POST
        assert 555 in state["tags"]  # marker tag applied
        client.update_document.assert_not_called()  # content untouched
        provider.transcribe_image.assert_not_called()  # no vision-OCR attempted
