"""
Image conversion for document OCR.

Converts raw document bytes (PDF, PNG, JPEG, TIFF, etc.) into a list of
PIL ``Image`` objects — one per page or frame.  This is a stateless,
pure-function module with no dependency on application settings or the
Paperless client, making it reusable in any image-processing pipeline.

Supported formats:

- **PDF** — rasterised via ``pdf2image`` (poppler) at a configurable DPI.
- **Single-frame images** (PNG, JPEG, BMP, …) — loaded via Pillow.
- **Multi-frame images** (TIFF, animated GIF, …) — expanded into one
  ``Image`` per frame.

Typical usage::

    from ocr.image_converter import bytes_to_images

    images = bytes_to_images(raw_pdf_bytes, "application/pdf", dpi=300)
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageSequence, UnidentifiedImageError
from pdf2image import convert_from_bytes


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
        RuntimeError: If the image bytes cannot be identified by Pillow.
    """
    if "pdf" in content_type.lower():
        return convert_from_bytes(content, dpi=dpi)

    try:
        img = Image.open(BytesIO(content))
        img.load()
        # Multi-frame image (TIFF, animated GIF, etc.)
        if getattr(img, "n_frames", 1) > 1:
            frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
            img.close()
            return frames
        # Single-frame image — copy so the BytesIO can be freed.
        single = img.copy()
        img.close()
        return [single]
    except UnidentifiedImageError as e:
        raise RuntimeError(f"Unable to open image: {e}") from e
