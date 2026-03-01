"""
OCR domain package.

Modules
-------
- **provider** — :class:`OcrProvider` ABC and :class:`OpenAIProvider` implementation.
- **worker** — :class:`DocumentProcessor` orchestrating single-document OCR.
- **image_converter** — raw bytes to PIL Images (PDF, TIFF, PNG, ...).
- **text_assembly** — per-page OCR results to assembled document text.
- **daemon** — long-running OCR daemon entry point.
- **prompts** — the system prompt sent to the vision-capable LLM.
"""

from .image_converter import bytes_to_images
from .provider import OcrProvider, OpenAIProvider
from .text_assembly import OCR_ERROR_MARKER, assemble_full_text
from .worker import DocumentProcessor

__all__ = [
    "DocumentProcessor",
    "OCR_ERROR_MARKER",
    "OcrProvider",
    "OpenAIProvider",
    "assemble_full_text",
    "bytes_to_images",
]
