"""Tests for classifier.metadata."""

from __future__ import annotations

import datetime as dt
from unittest.mock import patch

from classifier.metadata import (
    is_empty_classification,
    normalize_language,
    parse_document_date,
    resolve_date_for_tags,
    update_custom_fields,
)
from classifier.result import ClassificationResult


def _make_result(**overrides) -> ClassificationResult:
    """Build a ClassificationResult with sensible empty defaults."""
    defaults = {
        "title": "",
        "correspondent": "",
        "tags": [],
        "document_date": "",
        "document_type": "",
        "language": "",
        "person": "",
    }
    defaults.update(overrides)
    return ClassificationResult(**defaults)

class TestParseDocumentDate:
    """Tests for parse_document_date(value)."""

    def test_valid_iso_date(self):
        assert parse_document_date("2024-01-15") == "2024-01-15"

    def test_date_with_time_component(self):
        assert parse_document_date("2024-01-15T10:30:00") == "2024-01-15"

    def test_empty_string_returns_none(self):
        assert parse_document_date("") is None

    def test_invalid_date_returns_none(self):
        assert parse_document_date("not-a-date") is None

    def test_whitespace_only_returns_none(self):
        # After strip, "   " becomes "" which hits the falsy check after strip
        # Actually, the function checks `if not value` first, but "   " is truthy.
        # Then it strips and tries to parse -- "   ".strip() == ""
        # fromisoformat("") raises ValueError.
        assert parse_document_date("   ") is None

    def test_date_with_leading_trailing_whitespace(self):
        assert parse_document_date("  2024-06-01  ") == "2024-06-01"

    def test_invalid_date_logs_warning(self):
        with patch("classifier.metadata.log") as mock_log:
            result = parse_document_date("bad-date")
            assert result is None
            mock_log.warning.assert_called_once()

class TestResolveDateForTags:
    """Tests for resolve_date_for_tags(result_date, existing_date)."""

    def test_prefers_result_date_when_valid(self):
        result = resolve_date_for_tags("2024-03-01", "2023-12-01")
        assert result == "2024-03-01"

    def test_falls_back_to_existing_date(self):
        result = resolve_date_for_tags("", "2023-12-01")
        assert result == "2023-12-01"

    def test_falls_back_to_none_result_date(self):
        result = resolve_date_for_tags(None, "2023-12-01")
        assert result == "2023-12-01"

    def test_falls_back_to_today_when_both_invalid(self):
        result = resolve_date_for_tags("invalid", "also-invalid")
        assert result == dt.date.today().isoformat()

    def test_falls_back_to_today_when_both_empty(self):
        result = resolve_date_for_tags("", "")
        assert result == dt.date.today().isoformat()

    def test_falls_back_to_today_when_both_none(self):
        result = resolve_date_for_tags(None, None)
        assert result == dt.date.today().isoformat()

    def test_result_date_with_time_component(self):
        result = resolve_date_for_tags("2024-03-01T12:00:00", None)
        assert result == "2024-03-01"

class TestNormalizeLanguage:
    """Tests for normalize_language(language)."""

    def test_two_letter_code(self):
        assert normalize_language("en") == "en"

    def test_locale_with_hyphen(self):
        assert normalize_language("en-US") == "en"

    def test_locale_with_underscore(self):
        assert normalize_language("pt_BR") == "pt"

    def test_undetermined(self):
        assert normalize_language("und") == "und"

    def test_empty_string_returns_none(self):
        assert normalize_language("") is None

    def test_long_non_locale_returns_und(self):
        assert normalize_language("english") == "und"

    def test_two_letters_returned_as_is(self):
        assert normalize_language("de") == "de"
        assert normalize_language("fr") == "fr"

    def test_uppercase_normalized_to_lower(self):
        assert normalize_language("EN") == "en"

    def test_whitespace_stripped(self):
        assert normalize_language("  en  ") == "en"

    def test_three_letter_non_locale_returns_und(self):
        assert normalize_language("eng") == "und"

class TestUpdateCustomFields:
    """Tests for update_custom_fields(existing, field_id, value)."""

    def test_upserts_existing_field(self):
        existing = [{"field": 1, "value": "old"}, {"field": 2, "value": "keep"}]
        result = update_custom_fields(existing, 1, "new")
        assert result == [{"field": 1, "value": "new"}, {"field": 2, "value": "keep"}]

    def test_appends_new_field(self):
        existing = [{"field": 1, "value": "keep"}]
        result = update_custom_fields(existing, 2, "added")
        assert result == [{"field": 1, "value": "keep"}, {"field": 2, "value": "added"}]

    def test_handles_none_existing_list(self):
        result = update_custom_fields(None, 1, "value")
        assert result == [{"field": 1, "value": "value"}]

    def test_does_not_mutate_original(self):
        existing = [{"field": 1, "value": "old"}]
        original_copy = [{"field": 1, "value": "old"}]
        update_custom_fields(existing, 1, "new")
        assert existing == original_copy

    def test_empty_existing_list(self):
        result = update_custom_fields([], 5, "val")
        assert result == [{"field": 5, "value": "val"}]

class TestIsEmptyClassification:
    """Tests for is_empty_classification(result)."""

    def test_all_empty_fields_returns_true(self):
        result = _make_result()
        assert is_empty_classification(result) is True

    def test_has_title_returns_false(self):
        result = _make_result(title="Invoice")
        assert is_empty_classification(result) is False

    def test_has_tags_returns_false(self):
        result = _make_result(tags=["bills"])
        assert is_empty_classification(result) is False

    def test_whitespace_only_tags_returns_true(self):
        result = _make_result(tags=["  ", "\t"])
        assert is_empty_classification(result) is True

    def test_has_correspondent_returns_false(self):
        result = _make_result(correspondent="Acme")
        assert is_empty_classification(result) is False

    def test_has_document_type_returns_false(self):
        result = _make_result(document_type="Invoice")
        assert is_empty_classification(result) is False

    def test_has_person_returns_false(self):
        result = _make_result(person="John Doe")
        assert is_empty_classification(result) is False

    def test_has_language_returns_false(self):
        result = _make_result(language="en")
        assert is_empty_classification(result) is False

    def test_has_document_date_returns_false(self):
        result = _make_result(document_date="2024-01-01")
        assert is_empty_classification(result) is False

    def test_empty_tags_list_returns_true(self):
        result = _make_result(tags=[])
        assert is_empty_classification(result) is True
