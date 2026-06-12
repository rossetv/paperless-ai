"""Tests for ocr.image_converter."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest
from pdf2image.exceptions import (
    PDFPageCountError,
    PDFPopplerTimeoutError,
    PDFSyntaxError,
    PopplerNotInstalledError,
)
from PIL import Image

from ocr.image_converter import ImageConversionError, PageSource, open_page_source


def _make_png_bytes(width: int = 10, height: int = 10) -> bytes:
    """Create valid PNG bytes from a small image."""
    img = Image.new("RGB", (width, height), color="red")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_tiff_bytes(num_frames: int = 3) -> bytes:
    """Create valid multi-frame TIFF bytes."""
    frames = [Image.new("RGB", (10, 10), color=c) for c in ("red", "green", "blue")]
    buf = BytesIO()
    frames[0].save(
        buf, format="TIFF", save_all=True, append_images=frames[1:num_frames]
    )
    return buf.getvalue()


def _make_jpeg_bytes() -> bytes:
    """Create valid JPEG bytes."""
    img = Image.new("RGB", (10, 10), color="blue")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _load_all(source: PageSource) -> list[Image.Image]:
    """Load every page of a source into a list (for non-PDF, in-memory cases)."""
    return [source.load_page(i) for i in range(len(source))]


class TestBytesToImagesPng:
    def test_png_returns_source_of_one_image(self):
        png_bytes = _make_png_bytes()

        with open_page_source(png_bytes, "image/png") as source:
            assert len(source) == 1
            assert isinstance(source.load_page(0), Image.Image)

    def test_png_image_dimensions_preserved(self):
        png_bytes = _make_png_bytes(width=20, height=30)

        with open_page_source(png_bytes, "image/png") as source:
            assert source.load_page(0).size == (20, 30)

    def test_png_returns_usable_image(self):
        png_bytes = _make_png_bytes()

        with open_page_source(png_bytes, "image/png") as source:
            page = source.load_page(0)
            # Assert — result should be a usable image with correct dimensions
            assert page.size == (10, 10)
            assert page.mode in ("RGB", "RGBA", "L")


class TestBytesToImagesTiff:
    def test_tiff_multi_frame_returns_multiple_images(self):
        tiff_bytes = _make_tiff_bytes(num_frames=3)

        with open_page_source(tiff_bytes, "image/tiff") as source:
            assert len(source) == 3
            for img in _load_all(source):
                assert isinstance(img, Image.Image)

    def test_tiff_each_frame_is_independent(self):
        tiff_bytes = _make_tiff_bytes(num_frames=2)

        with open_page_source(tiff_bytes, "image/tiff") as source:
            assert source.load_page(0) is not source.load_page(1)

    def test_tiff_single_frame_returns_one_image(self):
        img = Image.new("RGB", (10, 10), color="red")
        buf = BytesIO()
        img.save(buf, format="TIFF")
        tiff_bytes = buf.getvalue()

        with open_page_source(tiff_bytes, "image/tiff") as source:
            assert len(source) == 1


class TestBytesToImagesPdf:
    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf_streams_via_output_folder(self, mock_convert):
        # paths_only=True makes poppler return file paths, not images.
        mock_convert.return_value = ["/tmp/page-1.png", "/tmp/page-2.png"]
        pdf_bytes = b"%PDF-1.4 fake content"

        source = open_page_source(pdf_bytes, "application/pdf")

        # The page count is known up front without loading any page.
        assert len(source) == 2
        # Streamed to a temp folder, paths returned, scaled to OCR_MAX_SIDE when
        # supplied (None here means "natural DPI" so size is omitted).
        mock_convert.assert_called_once()
        args, kwargs = mock_convert.call_args
        assert args == (pdf_bytes,)
        assert kwargs["dpi"] == 300
        assert kwargs["paths_only"] is True
        assert kwargs["fmt"] == "png"
        assert "output_folder" in kwargs
        assert "size" not in kwargs  # no max_side requested

    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf_custom_dpi(self, mock_convert):
        mock_convert.return_value = ["/tmp/page-1.png"]
        pdf_bytes = b"%PDF-1.4 fake"

        open_page_source(pdf_bytes, "application/pdf", dpi=150)

        assert mock_convert.call_args.kwargs["dpi"] == 150

    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf_max_side_scales_long_side(self, mock_convert):
        mock_convert.return_value = ["/tmp/page-1.png"]

        open_page_source(b"%PDF fake", "application/pdf", max_side=1600)

        # An int size maps to pdftoppm -scale-to, which caps the LONG side;
        # a (1600, None) tuple would only cap the width, so an int is required.
        assert mock_convert.call_args.kwargs["size"] == 1600

    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf_content_type_case_insensitive(self, mock_convert):
        mock_convert.return_value = []

        open_page_source(b"fake", "Application/PDF")

        mock_convert.assert_called_once()

    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf_content_type_with_charset(self, mock_convert):
        # Arrange — content type might include extra params
        mock_convert.return_value = []

        open_page_source(b"fake", "application/pdf; charset=utf-8")

        # Assert — still detected as PDF because "pdf" is in the string
        mock_convert.assert_called_once()

    @patch("ocr.image_converter.shutil.rmtree")
    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf_failure_cleans_temp_dir(self, mock_convert, mock_rmtree):
        # poppler blowing up must not strand the temp directory it was handed.
        mock_convert.side_effect = RuntimeError("poppler exploded")

        with pytest.raises(RuntimeError, match="poppler exploded"):
            open_page_source(b"%PDF fake", "application/pdf")

        mock_rmtree.assert_called_once()


class TestBytesToImagesInvalid:
    def test_invalid_bytes_raises_conversion_error(self):
        garbage = b"\x00\x01\x02\x03not-an-image"

        with pytest.raises(ImageConversionError, match="Unable to open image"):
            open_page_source(garbage, "image/png")

    def test_empty_bytes_raises_conversion_error(self):
        empty = b""

        with pytest.raises(ImageConversionError):
            open_page_source(empty, "image/png")


class TestBytesToImagesUnknownType:
    def test_unknown_type_attempts_image_open(self):
        # Arrange — use valid PNG bytes with a weird content type
        png_bytes = _make_png_bytes()

        with open_page_source(png_bytes, "application/octet-stream") as source:
            # Assert — should still work because Pillow can read it
            assert len(source) == 1
            assert isinstance(source.load_page(0), Image.Image)

    def test_jpeg_content_type(self):
        jpeg_bytes = _make_jpeg_bytes()

        with open_page_source(jpeg_bytes, "image/jpeg") as source:
            assert len(source) == 1
            assert isinstance(source.load_page(0), Image.Image)


class TestContentTypeMatching:
    @patch("ocr.image_converter.convert_from_bytes")
    def test_application_pdf_routes_to_pdf2image(self, mock_convert):
        mock_convert.return_value = []

        open_page_source(b"pdf-data", "application/pdf")

        mock_convert.assert_called_once()

    def test_image_png_routes_to_pillow(self):
        png_bytes = _make_png_bytes()

        with open_page_source(png_bytes, "image/png") as source:
            assert len(source) == 1

    def test_image_tiff_routes_to_pillow(self):
        tiff_bytes = _make_tiff_bytes(num_frames=2)

        with open_page_source(tiff_bytes, "image/tiff") as source:
            assert len(source) >= 2


class TestPageSourceLifecycle:
    """The PageSource contract: known count, lazy loads, owned cleanup."""

    def test_close_releases_in_memory_images(self):
        # close() releases the source's retained images. The image handed to
        # the caller by load_page is an independent copy (so the worker can
        # close it safely), so it stays usable after the source is closed —
        # mirroring the PDF path's no-open-handle contract.
        png_bytes = _make_png_bytes()
        source = open_page_source(png_bytes, "image/png")
        retained = source._images[0]
        page = source.load_page(0)

        source.close()

        # The source's own image is closed; a closed Pillow image raises on
        # any pixel operation.
        with pytest.raises(ValueError, match="closed image"):
            retained.load()
        # The caller's copy is independent and survives the close.
        assert page.size == (10, 10)
        assert page.convert("L").histogram() is not None
        page.close()

    def test_in_memory_load_page_returns_a_caller_owned_copy(self):
        # The worker closes every image it loads in a finally block. If
        # load_page handed back the object retained in _images, that close
        # would invalidate the source's own copy — a second load_page (e.g. a
        # cancelled-future retry) would then get a corrupted, closed image.
        png_bytes = _make_png_bytes()
        source = open_page_source(png_bytes, "image/png")

        first = source.load_page(0)
        first.close()  # mimic _ocr_one_page's finally block

        second = source.load_page(0)
        # The retained source image must survive the caller closing its copy.
        assert second.size == (10, 10)
        assert second.convert("L").histogram() is not None
        source.close()

    def test_close_is_idempotent(self):
        png_bytes = _make_png_bytes()
        source = open_page_source(png_bytes, "image/png")

        source.close()
        # Second close must not raise.
        source.close()

    def test_pdf_load_page_deletes_temp_file(self, tmp_path):
        # Two real one-pixel PNG files standing in for poppler's output.
        paths = []
        for i in range(2):
            p = tmp_path / f"page-{i}.png"
            Image.new("RGB", (4, 4), color="red").save(p)
            paths.append(str(p))

        source = PageSource(paths=paths, temp_dir=str(tmp_path))

        page = source.load_page(0)

        # Page is usable and the file backing it has been deleted (streamed).
        assert page.size == (4, 4)
        assert not (tmp_path / "page-0.png").exists()
        assert (tmp_path / "page-1.png").exists()
        page.close()
        source.close()

    def test_pdf_loaded_page_survives_source_close(self, tmp_path):
        p = tmp_path / "page-0.png"
        Image.new("RGB", (4, 4), color="blue").save(p)
        source = PageSource(paths=[str(p)], temp_dir=str(tmp_path))

        page = source.load_page(0)
        source.close()  # remove temp dir entirely

        # The loaded image must not depend on the now-deleted file.
        assert page.convert("L").histogram() is not None
        assert page.copy().size == (4, 4)
        page.close()

    def test_pdf_close_removes_temp_dir(self, tmp_path):
        sub = tmp_path / "ocr-temp"
        sub.mkdir()
        (sub / "page-0.png").write_bytes(b"junk")
        source = PageSource(paths=[str(sub / "page-0.png")], temp_dir=str(sub))

        source.close()

        assert not sub.exists()


class TestPdfRasterisationErrors:
    """H4: pdf2image failures are translated to ImageConversionError.

    None of the pdf2image / Poppler exceptions inherit from
    ImageConversionError, so they must be wrapped at the rasterisation
    boundary so the worker's ``except ImageConversionError`` branch fires,
    error-tags the document, and removes it from the queue.
    """

    @pytest.mark.parametrize(
        "exc_class",
        [PDFSyntaxError, PDFPageCountError, PopplerNotInstalledError],
    )
    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf2image_errors_become_image_conversion_error(
        self, mock_convert, exc_class
    ):
        mock_convert.side_effect = exc_class("simulated failure")

        with pytest.raises(ImageConversionError, match="PDF rasterisation failed"):
            open_page_source(b"%PDF fake", "application/pdf")

    @patch("ocr.image_converter.convert_from_bytes")
    def test_poppler_timeout_becomes_image_conversion_error(self, mock_convert):
        mock_convert.side_effect = PDFPopplerTimeoutError("timed out")

        with pytest.raises(ImageConversionError, match="PDF rasterisation failed"):
            open_page_source(b"%PDF fake", "application/pdf")

    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf2image_error_preserves_original_cause(self, mock_convert):
        original = PDFSyntaxError("corrupt stream")
        mock_convert.side_effect = original

        with pytest.raises(ImageConversionError) as exc_info:
            open_page_source(b"%PDF fake", "application/pdf")

        # The chain must be preserved so operators can diagnose the root cause
        # (CODE_GUIDELINES §6.3).
        assert exc_info.value.__cause__ is original

    @patch("ocr.image_converter.shutil.rmtree")
    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf2image_error_cleans_temp_dir(self, mock_convert, mock_rmtree):
        mock_convert.side_effect = PDFSyntaxError("corrupt")

        with pytest.raises(ImageConversionError):
            open_page_source(b"%PDF fake", "application/pdf")

        mock_rmtree.assert_called_once()

    @patch("ocr.image_converter.convert_from_bytes")
    def test_unexpected_exception_propagates_unchanged(self, mock_convert):
        # Errors that are not pdf2image domain exceptions (e.g. OOM) must
        # propagate unaltered — wrapping them would lose type information.
        mock_convert.side_effect = MemoryError("OOM")

        with pytest.raises(MemoryError):
            open_page_source(b"%PDF fake", "application/pdf")


class TestPdfTimeout:
    """L1: convert_from_bytes receives the timeout kwarg when requested."""

    @patch("ocr.image_converter.convert_from_bytes")
    def test_timeout_forwarded_to_convert_from_bytes(self, mock_convert):
        mock_convert.return_value = []

        open_page_source(b"%PDF fake", "application/pdf", timeout=60)

        assert mock_convert.call_args.kwargs["timeout"] == 60

    @patch("ocr.image_converter.convert_from_bytes")
    def test_no_timeout_omits_kwarg(self, mock_convert):
        mock_convert.return_value = []

        open_page_source(b"%PDF fake", "application/pdf")

        assert "timeout" not in mock_convert.call_args.kwargs

    @patch("ocr.image_converter.convert_from_bytes")
    def test_timeout_triggers_image_conversion_error(self, mock_convert):
        mock_convert.side_effect = PDFPopplerTimeoutError("pdftoppm timed out")

        with pytest.raises(ImageConversionError, match="PDF rasterisation failed"):
            open_page_source(b"%PDF fake", "application/pdf", timeout=1)


class TestTiffStreaming:
    """M6: multi-frame TIFF frames are streamed via temp files, not held in RAM.

    The streaming path mirrors the PDF strategy: each frame is saved to a
    temp PNG file, and the PageSource returns them one at a time from disk,
    so at most PAGE_WORKERS bitmaps are ever resident simultaneously.
    """

    def test_multiframe_tiff_uses_path_backed_page_source(self):
        tiff_bytes = _make_tiff_bytes(num_frames=3)

        with open_page_source(tiff_bytes, "image/tiff") as source:
            # The path-backed backing is used for multi-frame images.
            assert len(source._paths) == 3
            assert len(source._images) == 0

    def test_multiframe_tiff_all_frames_loadable(self):
        tiff_bytes = _make_tiff_bytes(num_frames=3)

        with open_page_source(tiff_bytes, "image/tiff") as source:
            assert len(source) == 3
            for i in range(len(source)):
                page = source.load_page(i)
                assert isinstance(page, Image.Image)
                assert page.size == (10, 10)
                page.close()

    def test_multiframe_tiff_temp_dir_removed_on_close(self, tmp_path):
        tiff_bytes = _make_tiff_bytes(num_frames=2)

        source = open_page_source(tiff_bytes, "image/tiff")
        temp_dir = source._temp_dir
        assert temp_dir is not None

        source.close()

        import os

        assert not os.path.exists(temp_dir)

    def test_multiframe_tiff_streaming_does_not_hold_all_frames_in_memory(self):
        # After open, the PageSource must hold paths — not decoded Image objects.
        # Holding all decoded frames would OOM-kill a container on large TIFFs.
        tiff_bytes = _make_tiff_bytes(num_frames=3)

        with open_page_source(tiff_bytes, "image/tiff") as source:
            assert source._images == []
            assert len(source._paths) == 3

    def test_single_frame_image_stays_in_memory(self):
        # Single-frame images are small; the in-memory path is kept for them
        # to avoid unnecessary temp-file overhead.
        png_bytes = _make_png_bytes()

        with open_page_source(png_bytes, "image/png") as source:
            assert len(source._images) == 1
            assert source._paths == []
