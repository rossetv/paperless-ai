"""Tests for OCR pipeline integration."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from ocr.image_converter import bytes_to_images
from ocr.text_assembly import assemble_full_text, OCR_ERROR_MARKER
from classifier.content_prep import truncate_content_by_pages
from tests.helpers.factories import make_png_bytes


def _make_tiff_bytes(num_frames: int = 3, width: int = 10, height: int = 10) -> bytes:
    """Create a multi-frame TIFF image as raw bytes."""
    frames = [Image.new("RGB", (width, height), color=c) for c in ["red", "green", "blue"][:num_frames]]
    buf = io.BytesIO()
    frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:])
    return buf.getvalue()

class TestFullOcrPipeline:
    """Real image conversion and text assembly with a mocked OCR provider."""

    def test_single_page_png_through_pipeline(self):
        """Convert a real PNG, mock-transcribe it, assemble the text."""
        png_bytes = make_png_bytes()
        images = bytes_to_images(png_bytes, "image/png")

        assert len(images) == 1

        # Simulate OCR provider returning transcription for each page
        page_results = [("Hello world from page 1.", "gpt-5-mini")]

        full_text, models = assemble_full_text(len(images), page_results)

        # Single page: no page headers
        assert "--- Page" not in full_text
        assert "Hello world from page 1." in full_text
        assert "Transcribed by model: gpt-5-mini" in full_text
        assert models == {"gpt-5-mini"}

    def test_multi_page_tiff_through_pipeline(self):
        """Convert a multi-frame TIFF, mock-transcribe pages, assemble text."""
        tiff_bytes = _make_tiff_bytes(num_frames=3)
        images = bytes_to_images(tiff_bytes, "image/tiff")

        assert len(images) == 3

        # Simulate transcription for each page with different models
        page_results = [
            ("Page one content.", "gpt-5-mini"),
            ("Page two content.", "gpt-5-mini"),
            ("Page three content.", "o4-mini"),
        ]

        full_text, models = assemble_full_text(len(images), page_results)

        # Multi-page: page headers expected
        assert "--- Page 1 ---" in full_text
        assert "--- Page 2 ---" in full_text
        assert "--- Page 3 ---" in full_text
        assert "Page one content." in full_text
        assert "Page two content." in full_text
        assert "Page three content." in full_text
        # Footer lists both models, sorted
        assert "Transcribed by model: gpt-5-mini, o4-mini" in full_text
        assert models == {"gpt-5-mini", "o4-mini"}

    def test_multi_page_with_page_model_headers(self):
        """Verify include_page_models adds model names to page headers."""
        # Simulate a 2-page document
        page_results = [
            ("First page.", "gpt-5-mini"),
            ("Second page.", "o4-mini"),
        ]

        full_text, models = assemble_full_text(
            page_count=2,
            page_results=page_results,
            include_page_models=True,
        )

        assert "--- Page 1 (gpt-5-mini) ---" in full_text
        assert "--- Page 2 (o4-mini) ---" in full_text
        assert models == {"gpt-5-mini", "o4-mini"}

class TestMultiPageMixedResults:
    """Test assembly when some pages are blank or produce empty text."""

    def test_blank_pages_skipped_in_assembly(self):
        """Blank pages (empty text) are omitted from the assembled output."""
        page_results = [
            ("First page content.", "gpt-5-mini"),
            ("", ""),            # blank page
            ("Third page content.", "gpt-5-mini"),
            ("   ", ""),         # whitespace-only page
        ]

        full_text, models = assemble_full_text(4, page_results)

        # Page 2 and 4 are blank, so only pages 1 and 3 have content
        assert "--- Page 1 ---" in full_text
        assert "--- Page 2 ---" not in full_text
        assert "--- Page 3 ---" in full_text
        assert "--- Page 4 ---" not in full_text
        assert "First page content." in full_text
        assert "Third page content." in full_text
        assert models == {"gpt-5-mini"}

    def test_all_blank_pages_produces_empty_text_with_no_footer(self):
        """When all pages are blank, the assembled text is empty."""
        page_results = [("", ""), ("", ""), ("  ", "")]

        full_text, models = assemble_full_text(3, page_results)

        assert full_text == ""
        assert models == set()

    def test_error_marker_pages_included(self):
        """Pages with OCR errors appear in the assembled text."""
        page_results = [
            ("Good content.", "gpt-5-mini"),
            (f"{OCR_ERROR_MARKER} Failed to OCR page 2.", ""),
        ]

        full_text, models = assemble_full_text(2, page_results)

        assert "Good content." in full_text
        assert OCR_ERROR_MARKER in full_text
        assert "Failed to OCR page 2." in full_text

class TestErrorPropagation:
    """Corrupt or invalid input triggers clear errors."""

    def test_corrupt_image_bytes_raises_runtime_error(self):
        """bytes_to_images raises RuntimeError for unidentifiable content."""
        with pytest.raises(RuntimeError, match="Unable to open image"):
            bytes_to_images(b"this is not an image", "image/png")

    def test_empty_bytes_raises_runtime_error(self):
        """Empty bytes are not a valid image."""
        with pytest.raises(RuntimeError, match="Unable to open image"):
            bytes_to_images(b"", "image/jpeg")

    def test_truncated_png_raises_error(self):
        """A truncated PNG file cannot be opened."""
        valid_png = make_png_bytes()
        truncated = valid_png[:20]  # cut off most of the file
        with pytest.raises((RuntimeError, Exception)):
            bytes_to_images(truncated, "image/png")

class TestContentPrepWithAssembly:
    """Test that assembled OCR text can be correctly truncated."""

    def test_truncated_content_preserves_footer(self):
        """Build multi-page OCR text, truncate it, verify footer survives."""
        # Build a realistic multi-page document
        page_results = [
            (f"Content for page {i}. " * 50, "gpt-5-mini")
            for i in range(1, 11)  # 10 pages
        ]

        full_text, _ = assemble_full_text(10, page_results)

        # Verify we have the expected structure
        assert "--- Page 1 ---" in full_text
        assert "--- Page 10 ---" in full_text
        assert "Transcribed by model: gpt-5-mini" in full_text

        # Truncate to first 3 pages with 2 tail pages
        truncated, note = truncate_content_by_pages(
            full_text,
            max_pages=3,
            tail_pages=2,
            headerless_char_limit=15000,
        )

        # Footer must survive truncation
        assert "Transcribed by model: gpt-5-mini" in truncated
        # We should have pages 1-3 (head) and pages 9-10 (tail)
        assert "--- Page 1 ---" in truncated
        assert "--- Page 2 ---" in truncated
        assert "--- Page 3 ---" in truncated
        assert "--- Page 9 ---" in truncated
        assert "--- Page 10 ---" in truncated
        # Middle pages should be removed
        assert "--- Page 5 ---" not in truncated
        assert "--- Page 6 ---" not in truncated
        # Truncation note should be present
        assert note is not None
        assert "truncated" in note.lower()

    def test_short_document_not_truncated(self):
        """A 2-page document within max_pages limit is returned unchanged."""
        page_results = [
            ("Short page one.", "gpt-5-mini"),
            ("Short page two.", "gpt-5-mini"),
        ]

        full_text, _ = assemble_full_text(2, page_results)

        truncated, note = truncate_content_by_pages(
            full_text,
            max_pages=3,
            tail_pages=2,
            headerless_char_limit=15000,
        )

        assert truncated == full_text
        assert note is None
