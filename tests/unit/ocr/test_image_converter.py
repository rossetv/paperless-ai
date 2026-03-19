"""Tests for ocr.image_converter."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from ocr.image_converter import bytes_to_images

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
    frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:num_frames])
    return buf.getvalue()

def _make_jpeg_bytes() -> bytes:
    """Create valid JPEG bytes."""
    img = Image.new("RGB", (10, 10), color="blue")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()

class TestBytesToImagesPng:
    def test_png_returns_list_of_one_image(self):
        png_bytes = _make_png_bytes()

        result = bytes_to_images(png_bytes, "image/png")

        assert len(result) == 1
        assert isinstance(result[0], Image.Image)

    def test_png_image_dimensions_preserved(self):
        png_bytes = _make_png_bytes(width=20, height=30)

        result = bytes_to_images(png_bytes, "image/png")

        assert result[0].size == (20, 30)

    def test_png_returns_usable_image(self):
        png_bytes = _make_png_bytes()

        result = bytes_to_images(png_bytes, "image/png")

        # Assert — result should be a usable image with correct dimensions
        assert result[0].size == (10, 10)
        assert result[0].mode in ("RGB", "RGBA", "L")

class TestBytesToImagesTiff:
    def test_tiff_multi_frame_returns_multiple_images(self):
        tiff_bytes = _make_tiff_bytes(num_frames=3)

        result = bytes_to_images(tiff_bytes, "image/tiff")

        assert len(result) == 3
        for img in result:
            assert isinstance(img, Image.Image)

    def test_tiff_each_frame_is_independent(self):
        tiff_bytes = _make_tiff_bytes(num_frames=2)

        result = bytes_to_images(tiff_bytes, "image/tiff")

        assert result[0] is not result[1]

    def test_tiff_single_frame_returns_one_image(self):
        img = Image.new("RGB", (10, 10), color="red")
        buf = BytesIO()
        img.save(buf, format="TIFF")
        tiff_bytes = buf.getvalue()

        result = bytes_to_images(tiff_bytes, "image/tiff")

        assert len(result) == 1

class TestBytesToImagesPdf:
    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf_delegates_to_convert_from_bytes(self, mock_convert):
        mock_images = [MagicMock(spec=Image.Image), MagicMock(spec=Image.Image)]
        mock_convert.return_value = mock_images
        pdf_bytes = b"%PDF-1.4 fake content"

        result = bytes_to_images(pdf_bytes, "application/pdf")

        mock_convert.assert_called_once_with(pdf_bytes, dpi=300)
        assert result == mock_images

    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf_custom_dpi(self, mock_convert):
        mock_convert.return_value = [MagicMock(spec=Image.Image)]
        pdf_bytes = b"%PDF-1.4 fake"

        bytes_to_images(pdf_bytes, "application/pdf", dpi=150)

        mock_convert.assert_called_once_with(pdf_bytes, dpi=150)

    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf_content_type_case_insensitive(self, mock_convert):
        mock_convert.return_value = []

        bytes_to_images(b"fake", "Application/PDF")

        mock_convert.assert_called_once()

    @patch("ocr.image_converter.convert_from_bytes")
    def test_pdf_content_type_with_charset(self, mock_convert):
        # Arrange — content type might include extra params
        mock_convert.return_value = []

        bytes_to_images(b"fake", "application/pdf; charset=utf-8")

        # Assert — still detected as PDF because "pdf" is in the string
        mock_convert.assert_called_once()

class TestBytesToImagesInvalid:
    def test_invalid_bytes_raises_runtime_error(self):
        garbage = b"\x00\x01\x02\x03not-an-image"

        with pytest.raises(RuntimeError, match="Unable to open image"):
            bytes_to_images(garbage, "image/png")

    def test_empty_bytes_raises_runtime_error(self):
        empty = b""

        with pytest.raises(RuntimeError):
            bytes_to_images(empty, "image/png")

class TestBytesToImagesUnknownType:
    def test_unknown_type_attempts_image_open(self):
        # Arrange — use valid PNG bytes with a weird content type
        png_bytes = _make_png_bytes()

        result = bytes_to_images(png_bytes, "application/octet-stream")

        # Assert — should still work because Pillow can read it
        assert len(result) == 1
        assert isinstance(result[0], Image.Image)

    def test_jpeg_content_type(self):
        jpeg_bytes = _make_jpeg_bytes()

        result = bytes_to_images(jpeg_bytes, "image/jpeg")

        assert len(result) == 1
        assert isinstance(result[0], Image.Image)

class TestContentTypeMatching:
    @patch("ocr.image_converter.convert_from_bytes")
    def test_application_pdf_routes_to_pdf2image(self, mock_convert):
        mock_convert.return_value = []

        bytes_to_images(b"pdf-data", "application/pdf")

        mock_convert.assert_called_once()

    def test_image_png_routes_to_pillow(self):
        png_bytes = _make_png_bytes()

        result = bytes_to_images(png_bytes, "image/png")

        assert len(result) == 1

    def test_image_tiff_routes_to_pillow(self):
        tiff_bytes = _make_tiff_bytes(num_frames=2)

        result = bytes_to_images(tiff_bytes, "image/tiff")

        assert len(result) >= 2
