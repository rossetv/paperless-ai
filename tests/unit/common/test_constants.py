"""Tests for common.constants."""

from __future__ import annotations

from common.constants import REFUSAL_PHRASES


class TestRefusalPhrases:
    """REFUSAL_PHRASES is the shared default for LLM-refusal detection."""

    def test_is_a_non_empty_tuple(self) -> None:
        assert isinstance(REFUSAL_PHRASES, tuple)
        assert len(REFUSAL_PHRASES) > 0

    def test_every_phrase_is_a_non_empty_string(self) -> None:
        for phrase in REFUSAL_PHRASES:
            assert isinstance(phrase, str)
            assert phrase, "a refusal phrase must not be empty"

    def test_every_phrase_is_lowercase(self) -> None:
        """Comparisons against these phrases are case-insensitive via lower().

        Storing the phrases pre-lowered keeps the matching logic a plain
        substring test rather than a per-comparison case fold.
        """
        for phrase in REFUSAL_PHRASES:
            assert phrase == phrase.lower()

    def test_includes_the_known_chatgpt_refusal_marker(self) -> None:
        # The classifier and OCR quality gates rely on this exact phrase.
        assert "chatgpt refused to transcribe" in REFUSAL_PHRASES
