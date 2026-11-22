"""Tests for ocr.image_converter."""

from __future__ import annotations

import os
import struct
import tempfile
import warnings
import zlib
from io import BytesIO
from unittest.mock import patch

import pytest
from pdf2image.exceptions import (
    PDFPageCountError,
    PDFPopplerTimeoutError,
    PDFSyntaxError,
    PopplerNotInstalledError,
)
from PIL import Image, ImageOps

from ocr.image_converter import ImageConversionError, PageSource, open_page_source


def _make_png_bytes(width: int = 10, height: int = 10) -> bytes:
    img = Image.new("RGB", (width, height), color="red")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_tiff_bytes(num_frames: int = 3) -> bytes:
    frames = [Image.new("RGB", (10, 10), color=c) for c in ("red", "green", "blue")]
    buf = BytesIO()
    frames[0].save(
        buf, format="TIFF", save_all=True, append_images=frames[1:num_frames]
    )
    return buf.getvalue()


def _make_jpeg_bytes() -> bytes:
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
        # Streamed to a temp folder as paths; without max_side, size is omitted.
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
        mock_convert.return_value = []

        open_page_source(b"fake", "application/pdf; charset=utf-8")

        # Still detected as PDF despite the parameters.
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
        png_bytes = _make_png_bytes()

        with open_page_source(png_bytes, "application/octet-stream") as source:
            # Pillow sniffs the format whatever the content type says.
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
    """pdf2image failures are translated to ImageConversionError.

    No pdf2image or Poppler exception inherits from it, so they are wrapped at
    the rasterisation boundary; the worker's ``except ImageConversionError``
    branch then error-tags the document and removes it from the queue.
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

        # The chain must be preserved so operators can diagnose the root cause.
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
    """convert_from_bytes receives the timeout kwarg when one is requested."""

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
    """Multi-frame TIFF frames are streamed via temp files, not held in RAM.

    The streaming path mirrors the PDF strategy: each frame is saved to a
    temp PNG file, and the PageSource returns them one at a time from disk,
    so at most PAGE_WORKERS bitmaps are ever resident simultaneously.
    """

    def test_multiframe_tiff_uses_path_backed_page_source(self):
        tiff_bytes = _make_tiff_bytes(num_frames=3)

        with open_page_source(tiff_bytes, "image/tiff") as source:
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


def _encode(images: list[Image.Image], fmt: str) -> bytes:
    buf = BytesIO()
    images[0].save(buf, format=fmt, save_all=len(images) > 1, append_images=images[1:])
    return buf.getvalue()


def _sixteen_bit(
    width: int, height: int, ink: int, paper: int, mode: str = "I;16"
) -> Image.Image:
    """A 16-bit greyscale page: an ink stripe on the left, paper elsewhere.

    *mode* "I;16B" saves as a big-endian ("MM") TIFF, which reopens as I;16B.
    """
    img = Image.new(mode, (width, height), paper)
    # Paste a 16-bit tile: an int fill into I;16 writes the low byte twice.
    img.paste(Image.new(mode, (width // 2, height), ink), (0, 0))
    return img


# Little- and big-endian 16-bit TIFFs reopen as different Pillow modes, and only
# I;16 supports point(); the converter must handle both.
_SIXTEEN_BIT_MODES = pytest.mark.parametrize("mode", ["I;16", "I;16B"])


class TestPageModeNormalisation:
    """Every page leaves the converter in a mode the provider can resize and PNG-encode.

    Pillow cannot thumbnail large I;16 images or write I/CMYK/YCbCr/... as PNG,
    so such scans would otherwise fail OCR at the provider.
    """

    @_SIXTEEN_BIT_MODES
    def test_sixteen_bit_single_image_is_scaled_to_8bit_not_clipped(self, mode):
        content = _encode(
            [_sixteen_bit(4, 2, ink=2000, paper=60000, mode=mode)], "TIFF"
        )

        with open_page_source(content, "image/tiff") as source:
            page = source.load_page(0)

        assert page.mode == "L"
        # 2000/257 ≈ 8 and 60000/257 ≈ 233 — a clip to 8 bits would give 255 for both.
        assert page.getpixel((0, 0)) == pytest.approx(8, abs=1)
        assert page.getpixel((3, 0)) == pytest.approx(233, abs=1)

    def test_sixteen_bit_large_scan_survives_provider_resize_and_encode(self):
        # I;16 thumbnail raises "image has wrong mode" once the reduce path kicks in.
        content = _encode([_sixteen_bit(5000, 7000, ink=2000, paper=60000)], "TIFF")

        with open_page_source(content, "image/tiff") as source:
            page = source.load_page(0)

        page.thumbnail((1600, 1600))
        page.save(BytesIO(), format="PNG")

    @_SIXTEEN_BIT_MODES
    def test_sixteen_bit_multiframe_tiff_is_scaled_to_8bit(self, mode):
        frames = [
            _sixteen_bit(4, 2, ink=2000, paper=60000, mode=mode) for _ in range(2)
        ]
        content = _encode(frames, "TIFF")

        with open_page_source(content, "image/tiff") as source:
            pages = _load_all(source)

        assert [p.mode for p in pages] == ["L", "L"]
        assert pages[1].getpixel((0, 0)) == pytest.approx(8, abs=1)
        assert pages[1].getpixel((3, 0)) == pytest.approx(233, abs=1)

    def test_32bit_greyscale_is_scaled_to_8bit(self):
        img = Image.new("I", (2, 1), 60000)
        img.putpixel((0, 0), 0)
        content = _encode([img], "TIFF")

        with open_page_source(content, "image/tiff") as source:
            page = source.load_page(0)

        assert page.mode == "L"
        assert page.getpixel((0, 0)) == 0
        assert page.getpixel((1, 0)) == pytest.approx(233, abs=1)

    @pytest.mark.parametrize(
        ("mode", "fmt", "expected"),
        [("CMYK", "JPEG", "RGB"), ("CMYK", "TIFF", "RGB"), ("LAB", "TIFF", "RGB")],
    )
    def test_colour_spaces_png_cannot_hold_become_rgb(self, mode, fmt, expected):
        content = _encode([Image.new(mode, (4, 4))], fmt)

        with open_page_source(content, "image/" + fmt.lower()) as source:
            page = source.load_page(0)

        assert page.mode == expected
        page.save(BytesIO(), format="PNG")

    def test_cmyk_multiframe_tiff_frames_become_rgb(self):
        content = _encode([Image.new("CMYK", (4, 4)) for _ in range(2)], "TIFF")

        with open_page_source(content, "image/tiff") as source:
            assert [p.mode for p in _load_all(source)] == ["RGB", "RGB"]

    @pytest.mark.parametrize("mode", ["1", "L", "LA", "P", "RGB", "RGBA"])
    def test_png_safe_modes_pass_through(self, mode):
        content = _encode([Image.new(mode, (4, 4))], "PNG")

        with open_page_source(content, "image/png") as source:
            assert source.load_page(0).mode == mode


class TestDecompressionBomb:
    """An image past Pillow's pixel cap is quarantined, not retried every poll."""

    def test_oversized_single_image_raises_conversion_error(self, monkeypatch):
        content = _make_png_bytes(width=100, height=100)
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # error above 2000 px

        with pytest.raises(ImageConversionError, match="Unable to open image"):
            open_page_source(content, "image/png")

    def test_oversized_later_tiff_frame_raises_and_cleans_temp_dir(self, monkeypatch):
        # Pillow checks each frame on seek(), so the bomb surfaces mid-iteration.
        content = _encode(
            [Image.new("RGB", (10, 10)), Image.new("RGB", (100, 100))], "TIFF"
        )
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
        created: list[str] = []
        real_mkdtemp = tempfile.mkdtemp
        monkeypatch.setattr(
            tempfile,
            "mkdtemp",
            lambda **kw: created.append(real_mkdtemp(**kw)) or created[-1],
        )

        with pytest.raises(ImageConversionError, match="Unable to open image"):
            open_page_source(content, "image/tiff")

        assert created and not os.path.exists(created[0])


def _header_only_png(width: int, height: int) -> bytes:
    """A PNG whose header claims *width* x *height* and carries no pixel data."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", b"")


class TestImagePixelCap:
    """An image above the pixel cap is refused outright, even where Pillow only warns."""

    def test_image_above_cap_but_inside_pillows_hard_limit_is_refused(
        self, monkeypatch
    ):
        # 22000 x 22000 is under twice the 250 MP cap, so Pillow only warns.
        content = _header_only_png(22000, 22000)
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 250_000_000)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pytest.raises(ImageConversionError, match="too large"):
                open_page_source(content, "image/png", max_side=1600)

    def test_image_at_the_cap_is_accepted(self, monkeypatch):
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

        with open_page_source(_make_png_bytes(10, 10), "image/png") as source:
            assert len(source) == 1

    def test_tiff_frame_above_cap_is_refused_and_cleans_temp_dir(self, monkeypatch):
        content = _encode(
            [Image.new("RGB", (10, 10)), Image.new("RGB", (40, 40))], "TIFF"
        )
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # 1600 px: warn only
        created: list[str] = []
        real_mkdtemp = tempfile.mkdtemp
        monkeypatch.setattr(
            tempfile,
            "mkdtemp",
            lambda **kw: created.append(real_mkdtemp(**kw)) or created[-1],
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pytest.raises(ImageConversionError, match="too large"):
                open_page_source(content, "image/tiff")

        assert created and not os.path.exists(created[0])


class TestImageMaxSide:
    """Image uploads are scaled to max_side like PDF pages are."""

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [("P", "RGB"), ("1", "L"), ("LA", "LA"), ("RGBA", "RGBA")],
    )
    def test_large_image_in_every_page_safe_mode_can_be_scaled(self, mode, expected):
        content = _encode([Image.new(mode, (300, 200))], "PNG")

        with open_page_source(content, "image/png", max_side=100) as source:
            page = source.load_page(0)

        assert page.size == (100, 67)
        assert page.mode == expected

    def test_shrunk_bilevel_scan_keeps_its_thin_strokes(self):
        img = Image.new("1", (3000, 2000), 1)
        for x in range(0, 3000, 10):
            img.paste(0, (x, 0, x + 1, 2000))
        content = _encode([img], "PNG")

        with open_page_source(content, "image/png", max_side=1000) as source:
            page = source.load_page(0)

        # Averaged strokes give greys; nearest sampling gives only black and white.
        assert sum(page.histogram()[1:255]) > 0

    def test_shrunk_palette_image_with_transparency_keeps_its_alpha(self):
        img = Image.new("P", (300, 200), 0)
        img.putpalette([255, 255, 255, 0, 0, 0])
        img.info["transparency"] = 0
        content = _encode([img], "PNG")

        with open_page_source(content, "image/png", max_side=100) as source:
            page = source.load_page(0)

        assert page.mode == "RGBA"

    def test_sixteen_bit_scan_is_never_widened_to_32_bit_at_full_size(self):
        content = _encode([_sixteen_bit(2000, 1000, ink=2000, paper=60000)], "TIFF")
        widened: list[int] = []
        original = Image.Image.convert

        def spy(self, mode=None, *args, **kwargs):
            if mode == "I":
                widened.append(self.width * self.height)
            return original(self, mode, *args, **kwargs)

        with patch.object(Image.Image, "convert", spy):
            with open_page_source(content, "image/tiff", max_side=500) as source:
                page = source.load_page(0)

        assert page.size == (500, 250) and page.mode == "L"
        assert max(widened) < 2000 * 1000

    def test_32bit_greyscale_is_shrunk_before_it_is_converted(self):
        content = _encode([Image.new("I", (2000, 1000), 60000)], "TIFF")
        converted: list[int] = []
        original = Image.Image.convert

        def spy(self, mode=None, *args, **kwargs):
            converted.append(self.width * self.height)
            return original(self, mode, *args, **kwargs)

        with patch.object(Image.Image, "convert", spy):
            with open_page_source(content, "image/tiff", max_side=500) as source:
                page = source.load_page(0)

        assert page.size == (500, 250) and page.mode == "L"
        assert max(converted) <= 500 * 250

    @pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
    def test_unreadable_exif_block_leaves_the_image_openable(self, fmt):
        buf = BytesIO()
        Image.new("RGB", (30, 20)).save(buf, format=fmt, exif=b"garbage")

        with open_page_source(buf.getvalue(), "image/x") as source:
            assert source.load_page(0).size == (30, 20)

    @pytest.mark.parametrize(
        ("orientation", "size"), [(1, (30, 20)), (6, (20, 30)), (3, (30, 20))]
    )
    def test_exif_orientation_is_applied_to_an_uploaded_photo(self, orientation, size):
        img = Image.new("RGB", (30, 20), "white")
        img.paste("red", (0, 0, 10, 10))
        exif = Image.Exif()
        exif[0x0112] = orientation
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=100, exif=exif)

        with open_page_source(buf.getvalue(), "image/jpeg") as source:
            page = source.load_page(0)

        assert page.size == size
        red_corner = {1: (2, 2), 6: (17, 2), 3: (27, 17)}[orientation]
        assert page.getpixel(red_corner)[0] > 200
        assert page.getpixel(red_corner)[1] < 80

    @pytest.mark.parametrize("fmt", ["PNG", "TIFF"])
    @pytest.mark.parametrize("orientation", [2, 3, 4, 5, 6, 7, 8])
    def test_orientation_pixels_match_pillows_own_transpose(self, orientation, fmt):
        img = Image.effect_noise((30, 20), 80).convert("RGB")
        exif = Image.Exif()
        exif[0x0112] = orientation
        buf = BytesIO()
        img.save(buf, format=fmt, exif=exif)
        expected = ImageOps.exif_transpose(Image.open(BytesIO(buf.getvalue())))

        with open_page_source(buf.getvalue(), "image/x") as source:
            page = source.load_page(0)

        assert page.tobytes() == expected.convert("RGB").tobytes()

    @pytest.mark.parametrize("orientation", [3, 6, 8])
    @pytest.mark.parametrize("compression", [None, "tiff_lzw", "tiff_adobe_deflate"])
    def test_a_tiff_is_turned_upright_once(self, orientation, compression):
        img = Image.effect_noise((30, 20), 80).convert("RGB")
        buf = BytesIO()
        img.save(
            buf,
            format="TIFF",
            compression=compression,
            tiffinfo={0x0112: orientation},
        )
        expected = ImageOps.exif_transpose(Image.open(BytesIO(buf.getvalue())))

        with open_page_source(buf.getvalue(), "image/tiff") as source:
            page = source.load_page(0)

        assert page.size == expected.size
        assert page.tobytes() == expected.convert("RGB").tobytes()

    def test_a_bilevel_group4_tiff_is_turned_upright_once(self):
        img = Image.effect_noise((30, 20), 80).convert("1")
        buf = BytesIO()
        img.save(buf, format="TIFF", compression="group4", tiffinfo={0x0112: 6})
        expected = ImageOps.exif_transpose(Image.open(BytesIO(buf.getvalue())))

        with open_page_source(buf.getvalue(), "image/tiff") as source:
            page = source.load_page(0)

        assert page.size == expected.size == (20, 30)
        assert page.convert("L").tobytes() == expected.convert("L").tobytes()

    def test_a_damaged_exif_tag_does_not_stop_a_rotated_jpeg_opening(self):
        # Orientation 6 plus tag 0x0115 typed ASCII: rewriting this EXIF raises.
        blob = (
            b"Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00\x03\x01\x15\x00\x02\x00\x00\x00\x04Cam\x00"
            b"\x01\x12\x00\x03\x00\x00\x00\x01\x00\x06\x00\x00"
        )
        buf = BytesIO()
        Image.new("RGB", (40, 30), "white").save(buf, format="JPEG", exif=blob)

        with open_page_source(buf.getvalue(), "image/jpeg") as source:
            assert source.load_page(0).size == (30, 40)

    @pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
    def test_large_image_is_scaled_to_max_side_keeping_aspect(self, fmt):
        content = _encode([Image.new("RGB", (3000, 2000))], fmt)

        with open_page_source(content, "image/x", max_side=1600) as source:
            page = source.load_page(0)

        assert max(page.size) == 1600
        assert page.size[1] == pytest.approx(1600 * 2000 / 3000, abs=1)

    def test_large_multiframe_tiff_frames_are_scaled_to_max_side(self):
        content = _encode([Image.new("RGB", (400, 800)) for _ in range(2)], "TIFF")

        with open_page_source(content, "image/tiff", max_side=200) as source:
            sizes = [p.size for p in _load_all(source)]

        assert sizes == [(100, 200), (100, 200)]

    def test_image_within_max_side_is_not_resized(self):
        with open_page_source(
            _make_png_bytes(20, 30), "image/png", max_side=1600
        ) as source:
            assert source.load_page(0).size == (20, 30)

    def test_without_max_side_the_image_keeps_its_size(self):
        content = _make_png_bytes(300, 200)

        with open_page_source(content, "image/png") as source:
            assert source.load_page(0).size == (300, 200)
