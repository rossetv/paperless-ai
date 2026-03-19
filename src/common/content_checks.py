"""Redaction-marker and refusal-phrase detection for OCR output."""

from __future__ import annotations

import re
from typing import Iterable

_REDACTED_RE = re.compile(r"\[[^\]]*redacted[^\]]*\]", re.IGNORECASE)


def contains_redacted_marker(text: str) -> bool:
    """Return ``True`` if *text* includes bracketed ``[REDACTED …]`` markers."""
    return bool(_REDACTED_RE.search(text))


def is_error_content(text: str, error_phrases: Iterable[str]) -> bool:
    """Return ``True`` if *text* contains a refusal phrase or redaction marker.

    Comparison is case-insensitive for both *text* and the phrases.
    """
    text_lower = text.lower()
    return contains_redacted_marker(text) or any(
        phrase.lower() in text_lower for phrase in error_phrases
    )
