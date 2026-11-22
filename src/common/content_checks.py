"""Redaction-marker and refusal-phrase detection for OCR output."""

from __future__ import annotations

import re
from typing import Iterable

_REDACTED_RE = re.compile(r"\[[^\]]*redacted[^\]]*\]", re.IGNORECASE)

# Written into a document's content when every vision model refuses it.
REFUSAL_MARK = "CHATGPT REFUSED TO TRANSCRIBE"

# Only a response shorter than this counts as a refusal on a soft phrase; a
# longer one may be real content that contains it (e.g. a denial letter).
_REFUSAL_DOMINANCE_THRESHOLD_CHARS = 200


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


def is_model_refusal(
    text: str, refusal_markers: Iterable[str], refusal_mark: str
) -> bool:
    """Return ``True`` only when *text* is a genuine model refusal.

    *refusal_mark*, the sentinel the prompt asks for, matches anywhere. A soft
    phrase (e.g. ``"i cannot assist"``) counts only in a short response, so a
    document that merely contains such language is not discarded. Also applied
    to a whole document's text, where redaction markers are checked separately.
    """
    text_lower = text.lower()

    if refusal_mark.lower() in text_lower:
        return True

    if len(text) >= _REFUSAL_DOMINANCE_THRESHOLD_CHARS:
        return False
    return any(phrase.lower() in text_lower for phrase in refusal_markers)
