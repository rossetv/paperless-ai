"""
Text and image content helpers.

Domain-specific utility functions for detecting blank pages, redaction
markers, and error/refusal content in OCR output.  These are used by
both the OCR and classification pipelines.

- :func:`is_blank` — detects near-white images that should be skipped.
- :func:`contains_redacted_marker` — detects ``[REDACTED ...]`` markers.
- :func:`is_error_content` — combines refusal-phrase and redaction detection.

Retry logic has been extracted to :mod:`common.retry`.
"""

from __future__ import annotations

import re
from typing import Iterable

from PIL import Image

# Pre-compiled at module level for efficiency — matches bracketed text
# containing the word "redacted" in any case, e.g. "[REDACTED]",
# "[NAME REDACTED]", "[REDACTED ADDRESS]".
_REDACTED_RE = re.compile(r"\[[^\]]*redacted[^\]]*\]", re.IGNORECASE)


def is_blank(image: Image.Image, threshold: int = 5) -> bool:
    """Return ``True`` if the image is essentially blank (all white).

    Converts to greyscale and checks that the number of non-white pixels
    is below *threshold*.  Used by the OCR provider to skip blank pages
    without wasting an API call.

    Args:
        image: A PIL Image to test.
        threshold: Maximum number of non-white pixels allowed.

    Returns:
        ``True`` if the image is blank.
    """
    histogram = image.convert("L").histogram()
    return (sum(histogram) - histogram[255]) < threshold


def contains_redacted_marker(text: str) -> bool:
    """Return ``True`` if *text* includes bracketed redaction markers.

    Examples of detected patterns::

        "[REDACTED]"
        "[REDACTED NAME]"
        "[NAME REDACTED]"

    Args:
        text: The text to search.

    Returns:
        ``True`` if at least one redaction marker is found.
    """
    return bool(_REDACTED_RE.search(text))


def is_error_content(text: str, error_phrases: Iterable[str]) -> bool:
    """Return ``True`` if *text* contains a refusal phrase or redaction marker.

    Used by the classification pipeline to detect OCR output that was stored
    as document content but actually represents a model refusal or error.

    Args:
        text: The document content to check.
        error_phrases: Lower-cased phrases that indicate an error/refusal.

    Returns:
        ``True`` if any refusal phrase or redaction marker is found.
    """
    text_lower = text.lower()
    return contains_redacted_marker(text) or any(
        phrase in text_lower for phrase in error_phrases
    )
