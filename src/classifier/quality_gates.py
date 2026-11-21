"""Quality gates for classification results and document content."""

from __future__ import annotations

from common.constants import REFUSAL_PHRASES
from common.content_checks import is_error_content
from .constants import GENERIC_DOCUMENT_TYPES
from .normalisers import normalise_simple


def is_generic_document_type(value: str) -> bool:
    """Return ``True`` if *value* is a vague placeholder like *"Document"*."""
    if not value:
        return True
    return normalise_simple(value) in GENERIC_DOCUMENT_TYPES


def needs_error_tag(text: str) -> bool:
    """Return ``True`` if *text* contains OCR refusal phrases or redaction markers.

    Catches documents whose body is error content the OCR daemon stored.
    """
    return is_error_content(text, REFUSAL_PHRASES)
