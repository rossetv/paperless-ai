"""Tests for classifier.tag_filters — dedup, filtering, and enrichment."""

from classifier.tag_filters import (
    dedupe_tags,
    enrich_tags,
    extract_model_tags,
    filter_blacklisted_tags,
    filter_redundant_tags,
    is_generic_document_type,
    needs_error_tag,
)


# ---------------------------------------------------------------------------
# dedupe_tags
# ---------------------------------------------------------------------------


def test_dedupe_tags_removes_case_duplicates():
    assert dedupe_tags(["Bills", "bills", "BILLS"]) == ["Bills"]


def test_dedupe_tags_preserves_order():
    assert dedupe_tags(["Z", "A", "z"]) == ["Z", "A"]


def test_dedupe_tags_drops_empty_and_whitespace():
    assert dedupe_tags(["", "  ", "Bills"]) == ["Bills"]


def test_dedupe_tags_strips_whitespace():
    assert dedupe_tags(["  Bills  ", "Payslip"]) == ["Bills", "Payslip"]


# ---------------------------------------------------------------------------
# is_generic_document_type
# ---------------------------------------------------------------------------


def test_is_generic_document_type_matches():
    assert is_generic_document_type("Document") is True
    assert is_generic_document_type("unknown") is True
    assert is_generic_document_type("N/A") is True
    assert is_generic_document_type("") is True


def test_is_generic_document_type_rejects():
    assert is_generic_document_type("Invoice") is False
    assert is_generic_document_type("Bank Statement") is False


# ---------------------------------------------------------------------------
# needs_error_tag
# ---------------------------------------------------------------------------


def test_needs_error_tag_refusal():
    assert needs_error_tag("I'm sorry, I can't assist with that.") is True


def test_needs_error_tag_redacted():
    assert needs_error_tag("[REDACTED NAME]") is True


def test_needs_error_tag_clean():
    assert needs_error_tag("Normal document content") is False


# ---------------------------------------------------------------------------
# extract_model_tags
# ---------------------------------------------------------------------------


def test_extract_model_tags_single():
    text = "content\n\nTranscribed by model: gpt-5-mini"
    assert extract_model_tags(text) == ["gpt-5-mini"]


def test_extract_model_tags_multiple():
    text = "content\n\nTranscribed by model: gpt-5-mini, o4-mini"
    assert extract_model_tags(text) == ["gpt-5-mini", "o4-mini"]


def test_extract_model_tags_no_footer():
    assert extract_model_tags("no footer here") == []


def test_extract_model_tags_deduplicates():
    text = (
        "--- Page 1 ---\nA\n\nTranscribed by model: gpt-5\n\n"
        "--- Page 2 ---\nB\n\nTranscribed by model: gpt-5"
    )
    assert extract_model_tags(text) == ["gpt-5"]


# ---------------------------------------------------------------------------
# filter_redundant_tags — additional edge cases
# ---------------------------------------------------------------------------


def test_filter_redundant_tags_empty_correspondent():
    tags = ["Bills", "Revolut"]
    filtered = filter_redundant_tags(tags, correspondent="", document_type="", person="")
    assert filtered == ["Bills", "Revolut"]


def test_filter_redundant_tags_company_suffix_match():
    tags = ["Revolut Ltd", "Bills"]
    filtered = filter_redundant_tags(
        tags, correspondent="Revolut", document_type="", person=""
    )
    assert filtered == ["Bills"]


# ---------------------------------------------------------------------------
# enrich_tags — edge cases
# ---------------------------------------------------------------------------


def test_enrich_tags_zero_limit_only_required():
    text = "content\n\nTranscribed by model: gpt-5"
    result = enrich_tags(["Bills", "Payslip"], text, "2024-01-01", "Ireland", 0)
    # Only required tags: model, year, country
    assert "gpt-5" in result
    assert "2024" in result
    assert "ireland" in result
    assert "bills" not in result
    assert "payslip" not in result


def test_enrich_tags_no_country():
    text = "content\n\nTranscribed by model: gpt-5"
    result = enrich_tags([], text, "2024-01-01", "", 5)
    assert "gpt-5" in result
    assert "2024" in result


def test_enrich_tags_lowercases():
    text = "content\n\nTranscribed by model: GPT-5"
    result = enrich_tags(["BILLS"], text, "2024-01-01", "", 5)
    assert "bills" in result
    assert "gpt-5" in result


# ---------------------------------------------------------------------------
# _extract_year — lines 228, 232-233: invalid date string returns None
# ---------------------------------------------------------------------------


def test_extract_year_invalid_date_returns_none():
    """An invalid (non-ISO) date string should return None (line 232-233)."""
    from classifier.tag_filters import _extract_year

    assert _extract_year("not-a-date") is None


def test_extract_year_empty_string_returns_none():
    """An empty string should return None (line 228)."""
    from classifier.tag_filters import _extract_year

    assert _extract_year("") is None


def test_extract_year_garbage_returns_none():
    """Garbage input like random text should return None."""
    from classifier.tag_filters import _extract_year

    assert _extract_year("hello world") is None


def test_extract_year_partial_date_returns_none():
    """A partial date without full ISO format should return None."""
    from classifier.tag_filters import _extract_year

    assert _extract_year("2024-13-45") is None
