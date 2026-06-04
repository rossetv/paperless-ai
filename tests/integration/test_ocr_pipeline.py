"""Tests for OCR pipeline integration."""

from __future__ import annotations

import io
import os
import shutil

import pytest
from PIL import Image

from ocr.image_converter import ImageConversionError, open_page_source
from ocr.text_assembly import OCR_ERROR_MARKER, PageResult, assemble_full_text
from classifier.content_prep import truncate_content_by_pages
from tests.helpers.factories import make_png_bytes


def _make_pdf_bytes(num_pages: int = 3, width: int = 300, height: int = 424) -> bytes:
    """Render a small multi-page PDF with a distinct mark per page.

    Each page carries a black square at a page-specific offset so a re-ordering
    bug (or a wrong page being loaded) would change the pixel content, not just
    the count. ``height > width`` makes the pages portrait, so the long-side
    scaling cap is exercised on the taller dimension.
    """
    pages = []
    for i in range(num_pages):
        page = Image.new("RGB", (width, height), color="white")
        for x in range(10 + i * 5, 40 + i * 5):
            for y in range(10, 40):
                page.putpixel((x, y), (0, 0, 0))
        pages.append(page)
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


def _make_tiff_bytes(num_frames: int = 3, width: int = 10, height: int = 10) -> bytes:
    """Create a multi-frame TIFF image as raw bytes."""
    frames = [
        Image.new("RGB", (width, height), color=c)
        for c in ["red", "green", "blue"][:num_frames]
    ]
    buf = io.BytesIO()
    frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:])
    return buf.getvalue()


class TestFullOcrPipeline:
    """Real image conversion and text assembly with a mocked OCR provider."""

    def test_single_page_png_through_pipeline(self):
        """Convert a real PNG, mock-transcribe it, assemble the text."""
        png_bytes = make_png_bytes()
        with open_page_source(png_bytes, "image/png") as source:
            assert len(source) == 1

            # Simulate OCR provider returning transcription for each page
            page_results = [PageResult("Hello world from page 1.", "gpt-5.4-mini")]

            full_text, models = assemble_full_text(len(source), page_results)

        # Single page: no page headers
        assert "--- Page" not in full_text
        assert "Hello world from page 1." in full_text
        assert "Transcribed by model: gpt-5.4-mini" in full_text
        assert models == {"gpt-5.4-mini"}

    def test_multi_page_tiff_through_pipeline(self):
        """Convert a multi-frame TIFF, mock-transcribe pages, assemble text."""
        tiff_bytes = _make_tiff_bytes(num_frames=3)
        with open_page_source(tiff_bytes, "image/tiff") as source:
            assert len(source) == 3
            page_count = len(source)

        # Simulate transcription for each page with different models
        page_results = [
            PageResult("Page one content.", "gpt-5.4-mini"),
            PageResult("Page two content.", "gpt-5.4-mini"),
            PageResult("Page three content.", "o4-mini"),
        ]

        full_text, models = assemble_full_text(page_count, page_results)

        # Multi-page: page headers expected
        assert "--- Page 1 ---" in full_text
        assert "--- Page 2 ---" in full_text
        assert "--- Page 3 ---" in full_text
        assert "Page one content." in full_text
        assert "Page two content." in full_text
        assert "Page three content." in full_text
        # Footer lists both models, sorted
        assert "Transcribed by model: gpt-5.4-mini, o4-mini" in full_text
        assert models == {"gpt-5.4-mini", "o4-mini"}

    def test_multi_page_with_page_model_headers(self):
        """Verify include_page_models adds model names to page headers."""
        # Simulate a 2-page document
        page_results = [
            PageResult("First page.", "gpt-5.4-mini"),
            PageResult("Second page.", "o4-mini"),
        ]

        full_text, models = assemble_full_text(
            page_count=2,
            page_results=page_results,
            include_page_models=True,
        )

        assert "--- Page 1 (gpt-5.4-mini) ---" in full_text
        assert "--- Page 2 (o4-mini) ---" in full_text
        assert models == {"gpt-5.4-mini", "o4-mini"}


class TestMultiPageMixedResults:
    """Test assembly when some pages are blank or produce empty text."""

    def test_blank_pages_skipped_in_assembly(self):
        """Blank pages (empty text) are omitted from the assembled output."""
        page_results = [
            PageResult("First page content.", "gpt-5.4-mini"),
            PageResult("", ""),  # blank page
            PageResult("Third page content.", "gpt-5.4-mini"),
            PageResult("   ", ""),  # whitespace-only page
        ]

        full_text, models = assemble_full_text(4, page_results)

        # Page 2 and 4 are blank, so only pages 1 and 3 have content
        assert "--- Page 1 ---" in full_text
        assert "--- Page 2 ---" not in full_text
        assert "--- Page 3 ---" in full_text
        assert "--- Page 4 ---" not in full_text
        assert "First page content." in full_text
        assert "Third page content." in full_text
        assert models == {"gpt-5.4-mini"}

    def test_all_blank_pages_produces_empty_text_with_no_footer(self):
        """When all pages are blank, the assembled text is empty."""
        page_results = [PageResult("", ""), PageResult("", ""), PageResult("  ", "")]

        full_text, models = assemble_full_text(3, page_results)

        assert full_text == ""
        assert models == set()

    def test_error_marker_pages_included(self):
        """Pages with OCR errors appear in the assembled text."""
        page_results = [
            PageResult("Good content.", "gpt-5.4-mini"),
            PageResult(f"{OCR_ERROR_MARKER} Failed to OCR page 2.", ""),
        ]

        full_text, models = assemble_full_text(2, page_results)

        assert "Good content." in full_text
        assert OCR_ERROR_MARKER in full_text
        assert "Failed to OCR page 2." in full_text


class TestErrorPropagation:
    """Corrupt or invalid input triggers clear errors."""

    def test_corrupt_image_bytes_raises_conversion_error(self):
        """open_page_source raises ImageConversionError for unidentifiable bytes."""
        with pytest.raises(ImageConversionError, match="Unable to open image"):
            open_page_source(b"this is not an image", "image/png")

    def test_empty_bytes_raises_conversion_error(self):
        """Empty bytes are not a valid image."""
        with pytest.raises(ImageConversionError, match="Unable to open image"):
            open_page_source(b"", "image/jpeg")

    def test_truncated_png_raises_error(self):
        """A truncated PNG file cannot be opened."""
        valid_png = make_png_bytes()
        truncated = valid_png[:20]  # cut off most of the file
        with pytest.raises(ImageConversionError):
            open_page_source(truncated, "image/png")


_POPPLER_AVAILABLE = shutil.which("pdftoppm") is not None


@pytest.mark.skipif(
    not _POPPLER_AVAILABLE, reason="poppler (pdftoppm) not installed on PATH"
)
class TestRealPopplerPdfStreaming:
    """End-to-end PDF rasterisation against the real poppler binary.

    The unit tests mock ``convert_from_bytes`` and so cannot catch the
    file-lifecycle bugs that motivated this module: a page handle that goes
    stale once its temp directory is cleaned, a wrong long-side scale, or a
    leaked temp directory. These exercise the genuine streamed path.

    This whole class FAILS against the broken "local TemporaryDirectory cleaned
    on return, hand out lazy file-backed images" variant: ``load_page`` -> pixel
    access in :meth:`test_pages_usable_through_to_assembly` would hit a missing
    file, and :meth:`test_temp_directory_cleaned_up_after_close` would find the
    directory already gone before the worker owned it.
    """

    def test_correct_page_count_and_order(self):
        pdf = _make_pdf_bytes(num_pages=3)

        with open_page_source(pdf, "application/pdf", max_side=1600) as source:
            assert len(source) == 3
            # Pages load in document order: each carries a mark shifted right by
            # page index, so the centre-of-mass of dark pixels moves rightwards.
            centres = []
            for i in range(len(source)):
                page = source.load_page(i)
                grey = page.convert("L")
                dark_xs = [
                    x
                    for x in range(grey.width)
                    for y in range(grey.height)
                    if grey.getpixel((x, y)) < 128
                ]
                centres.append(sum(dark_xs) / len(dark_xs))
                page.close()
        # Strictly increasing centre x-coordinate proves the order is preserved.
        assert centres[0] < centres[1] < centres[2]

    def test_long_side_capped_at_max_side(self):
        # Portrait page (taller than wide): the cap must apply to the HEIGHT.
        pdf = _make_pdf_bytes(num_pages=1, width=300, height=424)

        with open_page_source(pdf, "application/pdf", max_side=800) as source:
            page = source.load_page(0)
            assert max(page.size) == 800
            # Aspect ratio preserved (within rounding): width < height.
            assert page.size[0] < page.size[1]
            page.close()

    def test_pages_usable_through_to_assembly(self):
        # The critical lazy-cleanup regression test: load every page AFTER the
        # converter has returned, run the is_blank-style pixel access the
        # provider performs, and assemble text — all without the source open.
        pdf = _make_pdf_bytes(num_pages=2)

        source = open_page_source(pdf, "application/pdf", max_side=1600)
        page_count = len(source)
        page_results = []
        for i in range(page_count):
            page = source.load_page(i)
            # Exercises convert("L") — the access that crashes on a stale handle.
            non_white = sum(page.convert("L").histogram()[:255])
            assert non_white > 0  # the page mark survived rasterisation
            page_results.append(PageResult(f"Page {i + 1} text.", "test-model"))
            page.close()
        source.close()

        full_text, models = assemble_full_text(page_count, page_results)
        assert "--- Page 1 ---" in full_text
        assert "--- Page 2 ---" in full_text
        assert models == {"test-model"}

    def test_temp_files_deleted_as_pages_consumed(self):
        pdf = _make_pdf_bytes(num_pages=3)
        source = open_page_source(pdf, "application/pdf", max_side=1600)
        try:
            temp_dir = source._temp_dir
            assert temp_dir is not None
            remaining_before = len(os.listdir(temp_dir))

            source.load_page(0).close()

            # Consuming a page deletes its file, shrinking the temp dir.
            assert len(os.listdir(temp_dir)) == remaining_before - 1
        finally:
            source.close()

    def test_temp_directory_cleaned_up_after_close(self):
        pdf = _make_pdf_bytes(num_pages=2)
        source = open_page_source(pdf, "application/pdf", max_side=1600)
        temp_dir = source._temp_dir
        assert temp_dir is not None and os.path.isdir(temp_dir)

        source.close()

        # No leak: the directory the worker owned is gone after close.
        assert not os.path.exists(temp_dir)

    def test_natural_dpi_when_no_max_side(self):
        # Without a cap, pages render at the requested DPI (here a low DPI keeps
        # the test fast). Proves the size kwarg is genuinely optional.
        pdf = _make_pdf_bytes(num_pages=1, width=300, height=424)

        with open_page_source(pdf, "application/pdf", dpi=72) as source:
            page = source.load_page(0)
            # 300pt wide / 72dpi ~ a few hundred px; far below any 1600 cap.
            assert max(page.size) < 1600
            page.close()


class TestContentPrepWithAssembly:
    """Test that assembled OCR text can be correctly truncated."""

    def test_truncated_content_preserves_footer(self):
        """Build multi-page OCR text, truncate it, verify footer survives."""
        # Build a realistic multi-page document
        page_results = [
            PageResult(f"Content for page {i}. " * 50, "gpt-5.4-mini")
            for i in range(1, 11)  # 10 pages
        ]

        full_text, _ = assemble_full_text(10, page_results)

        # Verify we have the expected structure
        assert "--- Page 1 ---" in full_text
        assert "--- Page 10 ---" in full_text
        assert "Transcribed by model: gpt-5.4-mini" in full_text

        # Truncate to first 3 pages with 2 tail pages
        truncated, note = truncate_content_by_pages(
            full_text,
            max_pages=3,
            tail_pages=2,
            headerless_char_limit=15000,
        )

        # Footer must survive truncation
        assert "Transcribed by model: gpt-5.4-mini" in truncated
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
            PageResult("Short page one.", "gpt-5.4-mini"),
            PageResult("Short page two.", "gpt-5.4-mini"),
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
