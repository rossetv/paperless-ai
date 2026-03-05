"""Quality gates for classification results and document content."""

from __future__ import annotations

from common.utils import is_error_content
from .constants import ERROR_PHRASES, GENERIC_DOCUMENT_TYPES
from .normalizers import normalize_simple


def is_generic_document_type(value: str) -> bool:
    """
    Return ``True`` if *value* is a vague placeholder like *"Document"*.

    Used to reject low-quality classification results that would clutter the
    Paperless taxonomy.
    """
    if not value:
        return True
    return normalize_simple(value) in GENERIC_DOCUMENT_TYPES


def needs_error_tag(text: str) -> bool:
    """
    Return ``True`` if *text* contains OCR refusal phrases or redaction markers.

    This catches cases where the OCR daemon stored error content as the
    document body and the classifier receives it as input.
    """
    return is_error_content(text, ERROR_PHRASES)
