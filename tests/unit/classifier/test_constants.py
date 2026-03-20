"""Tests for classifier.constants."""

from __future__ import annotations

from common.constants import REFUSAL_PHRASES
from classifier.constants import (
    BLACKLISTED_TAGS,
    GENERIC_DOCUMENT_TYPES,
    MODEL_FOOTER_RE,
    PAGE_HEADER_RE,
)

class TestPageHeaderRe:
    """Tests for PAGE_HEADER_RE pattern."""

    def test_matches_simple_page_header(self):
        assert PAGE_HEADER_RE.search("--- Page 1 ---") is not None

    def test_matches_page_with_model_annotation(self):
        assert PAGE_HEADER_RE.search("--- Page 3 (gpt-5.4-mini) ---") is not None

    def test_matches_multidigit_page_number(self):
        assert PAGE_HEADER_RE.search("--- Page 42 ---") is not None

    def test_does_not_match_malformed_no_dashes(self):
        assert PAGE_HEADER_RE.search("Page 1") is None

    def test_does_not_match_missing_page_number(self):
        assert PAGE_HEADER_RE.search("--- Page ---") is None

    def test_does_not_match_partial_dashes(self):
        assert PAGE_HEADER_RE.search("-- Page 1 --") is None

    def test_matches_in_multiline_text(self):
        text = "Some content\n--- Page 2 ---\nMore content"
        assert PAGE_HEADER_RE.search(text) is not None

    def test_does_not_match_extra_text_on_line(self):
        assert PAGE_HEADER_RE.search("--- Page 1 --- extra") is None

class TestModelFooterRe:
    """Tests for MODEL_FOOTER_RE pattern."""

    def test_matches_single_model(self):
        match = MODEL_FOOTER_RE.search("Transcribed by model: gpt-5.4-mini")
        assert match is not None

    def test_captures_model_list(self):
        match = MODEL_FOOTER_RE.search("Transcribed by model: gpt-5.4-mini, o4-mini")
        assert match is not None
        assert match.group(1) == "gpt-5.4-mini, o4-mini"

    def test_case_insensitive(self):
        match = MODEL_FOOTER_RE.search("transcribed by model: gpt-5.4-mini")
        assert match is not None

    def test_no_match_without_prefix(self):
        assert MODEL_FOOTER_RE.search("model: gpt-5.4-mini") is None

class TestGenericDocumentTypes:
    """Tests for GENERIC_DOCUMENT_TYPES constant."""

    def test_is_frozenset(self):
        assert isinstance(GENERIC_DOCUMENT_TYPES, frozenset)

    def test_contains_expected_values(self):
        for value in ("document", "other", "unknown", "misc", "none", "general"):
            assert value in GENERIC_DOCUMENT_TYPES, f"{value!r} not in GENERIC_DOCUMENT_TYPES"

    def test_all_entries_are_lowercase(self):
        for value in GENERIC_DOCUMENT_TYPES:
            assert value == value.lower()

class TestBlacklistedTags:
    """Tests for BLACKLISTED_TAGS constant."""

    def test_is_frozenset(self):
        assert isinstance(BLACKLISTED_TAGS, frozenset)

    def test_contains_expected_values(self):
        for value in ("ai", "error", "new", "indexed"):
            assert value in BLACKLISTED_TAGS, f"{value!r} not in BLACKLISTED_TAGS"

    def test_all_entries_are_lowercase(self):
        for value in BLACKLISTED_TAGS:
            assert value == value.lower()

class TestErrorPhrases:
    """Tests for REFUSAL_PHRASES constant."""

    def test_is_tuple(self):
        assert isinstance(REFUSAL_PHRASES, tuple)

    def test_all_entries_are_strings(self):
        for phrase in REFUSAL_PHRASES:
            assert isinstance(phrase, str)

    def test_not_empty(self):
        assert len(REFUSAL_PHRASES) > 0

    def test_all_entries_are_lowercase(self):
        for phrase in REFUSAL_PHRASES:
            assert phrase == phrase.lower(), f"Phrase {phrase!r} is not lowercase"
