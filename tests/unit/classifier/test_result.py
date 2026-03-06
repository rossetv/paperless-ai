"""Tests for classifier.result."""

from __future__ import annotations

import json

import pytest

from classifier.result import _extract_json, parse_classification_response

class TestExtractJson:
    """Tests for _extract_json(text)."""

    def test_valid_json(self):
        result = _extract_json('{"title": "Invoice"}')
        assert result == {"title": "Invoice"}

    def test_json_in_markdown_fences(self):
        text = '```json\n{"title": "Invoice"}\n```'
        result = _extract_json(text)
        assert result == {"title": "Invoice"}

    def test_json_with_preamble_text(self):
        text = 'Here is the classification:\n{"title": "Invoice", "tags": []}'
        result = _extract_json(text)
        assert result == {"title": "Invoice", "tags": []}

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json("this is not json at all")

    def test_empty_string_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json("")

    def test_json_with_trailing_text(self):
        text = '{"title": "Test"}\nSome trailing text'
        result = _extract_json(text)
        assert result == {"title": "Test"}

    def test_no_closing_brace_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json('{"title": "Test"')

    def test_nested_json(self):
        text = '{"outer": {"inner": 1}}'
        result = _extract_json(text)
        assert result == {"outer": {"inner": 1}}

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
        assert result.tags == ["bills", "finance"]
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
        assert result.tags == ["bills"]

    def test_tags_as_empty_string(self):
        result = parse_classification_response(self._full_response(tags="   "))
        assert result.tags == []

    def test_tags_as_list_of_mixed_types(self):
        result = parse_classification_response(
            self._full_response(tags=["bills", 42, "finance"])
        )
        assert result.tags == ["bills", "42", "finance"]

    def test_tags_as_number_ignored(self):
        result = parse_classification_response(self._full_response(tags=42))
        assert result.tags == []

    def test_tags_as_none(self):
        result = parse_classification_response(self._full_response(tags=None))
        assert result.tags == []

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
        assert result.tags == ["bills", "finance"]

    def test_string_fields_are_stripped(self):
        result = parse_classification_response(
            self._full_response(title="  Padded Title  ")
        )
        assert result.title == "Padded Title"

    def test_missing_fields_default_to_empty(self):
        text = json.dumps({"title": "Test"})
        result = parse_classification_response(text)
        assert result.correspondent == ""
        assert result.tags == []
        assert result.document_date == ""
        assert result.document_type == ""
        assert result.language == ""
        assert result.person == ""
