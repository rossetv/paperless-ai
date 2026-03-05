"""OCR domain package."""

from __future__ import annotations

from .image_converter import bytes_to_images
from .provider import OcrProvider
from .text_assembly import OCR_ERROR_MARKER, assemble_full_text
from .worker import DocumentProcessor

__all__ = [
    "DocumentProcessor",
    "OCR_ERROR_MARKER",
    "OcrProvider",
    "assemble_full_text",
    "bytes_to_images",
]
