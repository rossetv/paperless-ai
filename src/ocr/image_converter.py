"""Converts document bytes (PDF, PNG, TIFF, etc.) into PIL Images for OCR."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageSequence, UnidentifiedImageError
from pdf2image import convert_from_bytes


class ImageConversionError(Exception):
    """Raised when raw document bytes cannot be decoded into images.

    The OCR daemon's domain error for an undecodable download — Pillow could
    not identify the bytes, or the file is truncated/corrupt. The worker
    catches this to mark the document as errored rather than letting a generic
    exception escape (CODE_GUIDELINES §6.1).
    """


def bytes_to_images(
    content: bytes, content_type: str, *, dpi: int = 300
) -> list[Image.Image]:
    """Convert raw document bytes into a list of PIL Images.

    - PDFs are rasterised into one image per page at *dpi* resolution.
    - Image formats (PNG/JPEG/TIFF/...) are loaded via Pillow.
    - Multi-frame images (e.g. TIFF) are expanded into one image per frame.

    All returned images are fully loaded into memory (``Image.load()``) so
    they do not depend on any open file handles.

    Args:
        content: The raw file bytes.
        content_type: MIME type (e.g. ``"application/pdf"``, ``"image/tiff"``).
        dpi: Resolution for PDF rasterisation (default 300).

    Returns:
        A list of PIL Images, one per page/frame.

    Raises:
        ImageConversionError: If the image bytes cannot be identified by Pillow
            or the file is truncated/corrupt.
    """
    if "pdf" in content_type.lower():
        return convert_from_bytes(content, dpi=dpi)

    try:
        img = Image.open(BytesIO(content))
        img.load()
        if getattr(img, "n_frames", 1) > 1:
            frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
            img.close()
            return frames
        # Copy the frame so the backing BytesIO can be released immediately.
        single = img.copy()
        img.close()
        return [single]
    except (UnidentifiedImageError, OSError) as e:
        # OSError covers a truncated or otherwise corrupt image — Pillow
        # identifies the format but fails partway through Image.load().
        raise ImageConversionError(f"Unable to open image: {e}") from e
