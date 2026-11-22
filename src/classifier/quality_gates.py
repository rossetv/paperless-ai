"""Quality gates for classification results and document content."""

from __future__ import annotations

from common.constants import REFUSAL_PHRASES
from common.content_checks import contains_redacted_marker
from ocr.provider import is_model_refusal
from .constants import GENERIC_DOCUMENT_TYPES
from .normalisers import normalise_simple

# What the OCR daemon writes into a document every model refused.
_REFUSAL_SENTINEL = "CHATGPT REFUSED TO TRANSCRIBE"


def is_generic_document_type(value: str) -> bool:
    """Return ``True`` if *value* is a vague placeholder like *"Document"*."""
    if not value:
        return True
    return normalise_simple(value) in GENERIC_DOCUMENT_TYPES


def needs_error_tag(text: str) -> bool:
    """Return ``True`` if *text* is a stored OCR refusal or has redaction markers.

    A soft refusal phrase counts only in short text, as at the OCR page level, so
    a long real document that quotes one is kept.
    """
    return contains_redacted_marker(text) or is_model_refusal(
        text, REFUSAL_PHRASES, _REFUSAL_SENTINEL
    )
