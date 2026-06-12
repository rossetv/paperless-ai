"""Tests for classifier.result.

The JSON-extraction behaviour parse_classification_response relies on is the
shared ``common.llm.extract_json_object`` helper; its own tests live in
tests/unit/common/test_llm.py.
"""

from __future__ import annotations

import json

import pytest

from classifier.result import parse_classification_response


class TestParseClassificationResponse:
    """Tests for parse_classification_response(text)."""

    def _full_response(self, **overrides):
        data = {
            "title": "Invoice 2024",
            "correspondent": "Acme Corp",
            "tags": ["bills", "finance"],
            "document_date": "2024-01-15",
            "document_type": "Invoice",
            "language": "en",
            "person": "John Doe",
        }
        data.update(overrides)
        return json.dumps(data)

    def test_full_valid_response(self):
        result = parse_classification_response(self._full_response())
        assert result.title == "Invoice 2024"
        assert result.correspondent == "Acme Corp"
        assert result.tags == ("bills", "finance")
        assert result.document_date == "2024-01-15"
        assert result.document_type == "Invoice"
        assert result.language == "en"
        assert result.person == "John Doe"

    def test_null_values_converted_to_empty_strings(self):
        result = parse_classification_response(
            self._full_response(title=None, correspondent=None, person=None)
        )
        assert result.title == ""
        assert result.correspondent == ""
        assert result.person == ""

    def test_tags_as_single_string(self):
        result = parse_classification_response(self._full_response(tags="bills"))
        assert result.tags == ("bills",)

    def test_tags_as_empty_string(self):
        result = parse_classification_response(self._full_response(tags="   "))
        assert result.tags == ()

    def test_tags_as_list_of_mixed_types(self):
        result = parse_classification_response(
            self._full_response(tags=["bills", 42, "finance"])
        )
        assert result.tags == ("bills", "42", "finance")

    def test_tags_as_number_ignored(self):
        result = parse_classification_response(self._full_response(tags=42))
        assert result.tags == ()

    def test_tags_as_none(self):
        result = parse_classification_response(self._full_response(tags=None))
        assert result.tags == ()

    def test_empty_response_raises_value_error(self):
        with pytest.raises(ValueError, match="empty"):
            parse_classification_response("")

    def test_non_object_json_raises_value_error(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            parse_classification_response("[1, 2, 3]")

    def test_whitespace_only_response_raises_value_error(self):
        with pytest.raises(ValueError, match="empty"):
            parse_classification_response("   \n\t  ")

    def test_classification_result_is_frozen(self):
        result = parse_classification_response(self._full_response())
        with pytest.raises(AttributeError):
            result.title = "Changed"

    def test_tags_with_whitespace_only_entries_dropped(self):
        result = parse_classification_response(
            self._full_response(tags=["bills", "  ", "", "finance"])
        )
        assert result.tags == ("bills", "finance")

    def test_string_fields_are_stripped(self):
        result = parse_classification_response(
            self._full_response(title="  Padded Title  ")
        )
        assert result.title == "Padded Title"

    def test_missing_fields_default_to_empty(self):
        text = json.dumps({"title": "Test"})
        result = parse_classification_response(text)
        assert result.correspondent == ""
        assert result.tags == ()
        assert result.document_date == ""
        assert result.document_type == ""
        assert result.language == ""
        assert result.person == ""

    def test_bool_false_document_type_treated_as_absent(self):
        """On providers without JSON-schema enforcement the LLM may return
        ``false`` for a text field.  It must be treated as absent (empty
        string), not coerced to the string "False"."""
        result = parse_classification_response(self._full_response(document_type=False))
        assert result.document_type == ""
        assert result.document_type != "False"

    def test_bool_true_field_treated_as_absent(self):
        result = parse_classification_response(self._full_response(correspondent=True))
        assert result.correspondent == ""

    def test_int_field_treated_as_absent(self):
        result = parse_classification_response(self._full_response(title=0))
        assert result.title == ""
        assert result.title != "0"

    def test_float_field_treated_as_absent(self):
        result = parse_classification_response(self._full_response(language=1.5))
        assert result.language == ""

    def test_string_fields_still_parsed_correctly(self):
        """OpenAI schema-enforced responses always deliver strings — verify no
        regression."""
        result = parse_classification_response(self._full_response())
        assert result.document_type == "Invoice"
        assert result.title == "Invoice 2024"
