"""Regex patterns, frozen sets, and phrase lists for the classification pipeline."""

from __future__ import annotations

import re

# Matches OCR output headers like ``--- Page 3 ---`` or
# ``--- Page 3 (gpt-5-mini) ---``.
PAGE_HEADER_RE: re.Pattern[str] = re.compile(
    r"^--- Page \d+(?: \([^)]+\))? ---$", re.MULTILINE
)

# Matches the footer line the OCR daemon appends, e.g.
# ``Transcribed by model: gpt-5-mini, o4-mini``.
MODEL_FOOTER_RE: re.Pattern[str] = re.compile(
    r"transcribed by model:\s*(.+)", re.IGNORECASE
)


# Document types that are too vague to be useful.  When the LLM returns one
# of these we treat the classification as failed.
GENERIC_DOCUMENT_TYPES: frozenset[str] = frozenset({
    "document",
    "documents",
    "general",
    "misc",
    "miscellaneous",
    "n/a",
    "na",
    "none",
    "other",
    "unknown",
    "unspecified",
})

# Tags that should never appear in the final tag set — they collide with
# Paperless-internal labels or automation markers.
BLACKLISTED_TAGS: frozenset[str] = frozenset({
    "ai",
    "error",
    "indexed",
    "new",
})
