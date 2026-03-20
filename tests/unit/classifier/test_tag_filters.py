"""Tests for classifier.tag_filters."""

from __future__ import annotations

import datetime as dt

from classifier.quality_gates import is_generic_document_type, needs_error_tag
from classifier.tag_filters import (
    dedupe_tags,
    enrich_tags,
    extract_model_tags,
    filter_blacklisted_tags,
    filter_redundant_tags,
)

class TestDedupeTags:
    """Tests for dedupe_tags(tags)."""

    def test_deduplicates_case_insensitively(self):
        result = dedupe_tags(["Bills", "bills", "BILLS"])
        assert result == ["Bills"]

    def test_preserves_first_occurrence(self):
        result = dedupe_tags(["bills", "Bills", "BILLS"])
        assert result == ["bills"]

    def test_drops_empty_and_whitespace(self):
        result = dedupe_tags(["", "  ", "bills", "\t"])
        assert result == ["bills"]

    def test_preserves_order(self):
        result = dedupe_tags(["c", "a", "b"])
        assert result == ["c", "a", "b"]

    def test_empty_input(self):
        assert dedupe_tags([]) == []

    def test_strips_whitespace(self):
        result = dedupe_tags(["  bills  ", "finance"])
        assert result == ["bills", "finance"]

class TestFilterBlacklistedTags:
    """Tests for filter_blacklisted_tags(tags)."""

    def test_removes_blacklisted_tags(self):
        result = filter_blacklisted_tags(["AI", "error", "new", "indexed", "Bills"])
        assert result == ["Bills"]

    def test_keeps_non_blacklisted(self):
        result = filter_blacklisted_tags(["Finance", "Tax"])
        assert result == ["Finance", "Tax"]

    def test_case_insensitive(self):
        result = filter_blacklisted_tags(["ai", "AI", "Ai", "Bills"])
        assert result == ["Bills"]

    def test_empty_input(self):
        assert filter_blacklisted_tags([]) == []

class TestFilterRedundantTags:
    """Tests for filter_redundant_tags(tags, correspondent, document_type, person)."""

    def test_removes_tag_matching_correspondent(self):
        result = filter_redundant_tags(
            ["Revolut", "Bills"], correspondent="Revolut", document_type="", person=""
        )
        assert result == ["Bills"]

    def test_removes_tag_matching_correspondent_with_suffix(self):
        """Tag 'Revolut Ltd' should be removed when correspondent is 'Revolut'."""
        result = filter_redundant_tags(
            ["Revolut Ltd", "Bills"], correspondent="Revolut", document_type="", person=""
        )
        assert result == ["Bills"]

    def test_removes_tag_matching_document_type(self):
        result = filter_redundant_tags(
            ["Invoice", "Bills"], correspondent="", document_type="Invoice", person=""
        )
        assert result == ["Bills"]

    def test_removes_tag_matching_person(self):
        result = filter_redundant_tags(
            ["John Doe", "Bills"], correspondent="", document_type="", person="John Doe"
        )
        assert result == ["Bills"]

    def test_keeps_non_redundant_tags(self):
        result = filter_redundant_tags(
            ["Finance", "Tax"], correspondent="Acme", document_type="Invoice", person="Jane"
        )
        assert result == ["Finance", "Tax"]

    def test_all_empty_context(self):
        result = filter_redundant_tags(
            ["Bills", "Tax"], correspondent="", document_type="", person=""
        )
        assert result == ["Bills", "Tax"]

    def test_deduplicates_first(self):
        result = filter_redundant_tags(
            ["Bills", "bills", "Tax"], correspondent="", document_type="", person=""
        )
        assert result == ["Bills", "Tax"]

class TestIsGenericDocumentType:
    """Tests for is_generic_document_type(value)."""

    def test_document_is_generic(self):
        assert is_generic_document_type("Document") is True

    def test_invoice_is_not_generic(self):
        assert is_generic_document_type("Invoice") is False

    def test_empty_string_is_generic(self):
        assert is_generic_document_type("") is True

    def test_case_insensitive(self):
        assert is_generic_document_type("DOCUMENT") is True
        assert is_generic_document_type("document") is True

    def test_other_is_generic(self):
        assert is_generic_document_type("Other") is True

    def test_unknown_is_generic(self):
        assert is_generic_document_type("Unknown") is True

    def test_specific_type_not_generic(self):
        assert is_generic_document_type("Bank Statement") is False

class TestNeedsErrorTag:
    """Tests for needs_error_tag(text)."""

    def test_refusal_text(self):
        assert needs_error_tag("I'm sorry, I can't assist with that.") is True

    def test_clean_text(self):
        assert needs_error_tag("This is a normal invoice from Acme Corp.") is False

    def test_redacted_text(self):
        assert needs_error_tag("Customer name: [REDACTED]") is True

    def test_empty_text(self):
        assert needs_error_tag("") is False

    def test_chatgpt_refused(self):
        assert needs_error_tag("ChatGPT refused to transcribe this document.") is True

class TestExtractModelTags:
    """Tests for extract_model_tags(text)."""

    def test_single_model(self):
        text = "Content\n\nTranscribed by model: gpt-5.4-mini"
        result = extract_model_tags(text)
        assert result == ["gpt-5.4-mini"]

    def test_multiple_models(self):
        text = "Content\n\nTranscribed by model: gpt-5.4-mini, o4-mini"
        result = extract_model_tags(text)
        assert result == ["gpt-5.4-mini", "o4-mini"]

    def test_no_footer(self):
        result = extract_model_tags("Just normal text, no footer.")
        assert result == []

    def test_deduplicates(self):
        text = (
            "Page 1\n\nTranscribed by model: gpt-5.4-mini\n"
            "Page 2\n\nTranscribed by model: gpt-5.4-mini"
        )
        result = extract_model_tags(text)
        assert result == ["gpt-5.4-mini"]

    def test_multiple_footers_different_models(self):
        text = (
            "Page 1\n\nTranscribed by model: gpt-5.4-mini\n"
            "Page 2\n\nTranscribed by model: o4-mini"
        )
        result = extract_model_tags(text)
        assert result == ["gpt-5.4-mini", "o4-mini"]

class TestEnrichTags:
    """Tests for enrich_tags(tags, text, document_date, default_country_tag, tag_limit)."""

    def test_adds_year_tag_from_date(self):
        result = enrich_tags(
            tags=["bills"],
            text="Some text",
            document_date="2024-06-15",
            default_country_tag="",
            tag_limit=10,
        )
        assert "2024" in result

    def test_adds_country_tag_when_configured(self):
        result = enrich_tags(
            tags=["bills"],
            text="Some text",
            document_date="2024-01-01",
            default_country_tag="sweden",
            tag_limit=10,
        )
        assert "sweden" in result

    def test_adds_model_tags_from_text(self):
        text = "Content\n\nTranscribed by model: gpt-5.4-mini"
        result = enrich_tags(
            tags=["bills"],
            text=text,
            document_date="2024-01-01",
            default_country_tag="",
            tag_limit=10,
        )
        assert "gpt-5.4-mini" in result

    def test_enforces_tag_limit_on_non_required(self):
        result = enrich_tags(
            tags=["a", "b", "c", "d", "e"],
            text="Some text",
            document_date="2024-01-01",
            default_country_tag="",
            tag_limit=2,
        )
        # Required: year tag "2024"
        # Non-required: capped to 2
        non_required = [t for t in result if t != "2024"]
        assert len(non_required) <= 2

    def test_required_tags_not_counted_against_limit(self):
        text = "Content\n\nTranscribed by model: gpt-5.4-mini"
        result = enrich_tags(
            tags=["bills"],
            text=text,
            document_date="2024-01-01",
            default_country_tag="sweden",
            tag_limit=1,
        )
        # Required: gpt-5.4-mini, 2024, sweden (3 tags)
        # Non-required: "bills" capped to 1
        assert "gpt-5.4-mini" in result
        assert "2024" in result
        assert "sweden" in result
        assert "bills" in result

    def test_returns_lowercased_tags(self):
        result = enrich_tags(
            tags=["Bills", "FINANCE"],
            text="text",
            document_date="2024-01-01",
            default_country_tag="",
            tag_limit=10,
        )
        for tag in result:
            assert tag == tag.lower(), f"Tag {tag!r} is not lowercase"

    def test_deduplicates_across_required_and_optional(self):
        result = enrich_tags(
            tags=["2024", "bills"],
            text="text",
            document_date="2024-01-01",
            default_country_tag="",
            tag_limit=10,
        )
        assert result.count("2024") == 1

    def test_tag_limit_zero_drops_all_non_required(self):
        result = enrich_tags(
            tags=["bills", "finance"],
            text="text",
            document_date="2024-01-01",
            default_country_tag="",
            tag_limit=0,
        )
        # Only required tags remain (year)
        assert "bills" not in result
        assert "finance" not in result
        assert "2024" in result

    def test_year_falls_back_to_current_year(self):
        result = enrich_tags(
            tags=[],
            text="text",
            document_date="",
            default_country_tag="",
            tag_limit=10,
        )
        current_year = dt.date.today().strftime("%Y")
        assert current_year in result

    def test_no_country_tag_when_empty(self):
        result = enrich_tags(
            tags=["bills"],
            text="text",
            document_date="2024-01-01",
            default_country_tag="",
            tag_limit=10,
        )
        # Only year + bills expected, no country
        assert len(result) == 2

    def test_negative_tag_limit_treated_as_zero(self):
        result = enrich_tags(
            tags=["bills", "finance"],
            text="text",
            document_date="2024-01-01",
            default_country_tag="",
            tag_limit=-5,
        )
        assert "bills" not in result
        assert "finance" not in result

    def test_invalid_date_falls_back_to_current_year(self):
        # _extract_year returns None for invalid dates
        result = enrich_tags(
            tags=[],
            text="text",
            document_date="not-a-date",
            default_country_tag="",
            tag_limit=5,
        )
        current_year = dt.date.today().strftime("%Y")
        assert current_year in result
