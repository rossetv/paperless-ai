"""Shared constants for refusal/error detection across OCR and classification."""

from __future__ import annotations

# Phrases that indicate an LLM refusal or policy block.
# Used as the default for OCR_REFUSAL_MARKERS (configurable via env var) and
# for the classifier's content quality gate.  All comparisons are case-insensitive.
REFUSAL_PHRASES: tuple[str, ...] = (
    "i can't assist",
    "i cannot assist",
    "i can't help with transcrib",
    "i cannot help with transcrib",
    "i'm sorry, i can't assist with that.",
    "chatgpt refused to transcribe",
)
