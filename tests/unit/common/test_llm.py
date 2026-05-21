"""Tests for common.llm — unique_models, extract_json_object, and _create_completion.

Model-fallback and retry/limiter integration tests live in
test_llm_fallback.py (§3.1 500-line ceiling split).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from common.llm import (
    OpenAIChatMixin,
    extract_json_object,
    unique_models,
    _openai_holder,
)

class TestUniqueModels:

    def test_deduplicates_preserving_order(self):
        result = unique_models(["a", "b", "a", "c", "b"])
        assert result == ["a", "b", "c"]

    def test_empty_list(self):
        assert unique_models([]) == []

    def test_all_duplicates(self):
        result = unique_models(["x", "x", "x"])
        assert result == ["x"]

    def test_no_duplicates(self):
        result = unique_models(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_single_element(self):
        assert unique_models(["only"]) == ["only"]

    def test_preserves_insertion_order(self):
        result = unique_models(["c", "b", "a", "c", "a"])
        assert result == ["c", "b", "a"]


class TestExtractJsonObject:
    """Tests for the shared extract_json_object(text) LLM-output parser."""

    def test_valid_json_object(self):
        assert extract_json_object('{"title": "Invoice"}') == {"title": "Invoice"}

    def test_json_in_markdown_fences(self):
        text = '```json\n{"title": "Invoice"}\n```'
        assert extract_json_object(text) == {"title": "Invoice"}

    def test_json_in_bare_fences(self):
        text = '```\n{"title": "Invoice"}\n```'
        assert extract_json_object(text) == {"title": "Invoice"}

    def test_json_with_preamble_text(self):
        text = 'Here is the classification:\n{"title": "Invoice", "tags": []}'
        assert extract_json_object(text) == {"title": "Invoice", "tags": []}

    def test_json_with_trailing_text(self):
        text = '{"title": "Test"}\nSome trailing text'
        assert extract_json_object(text) == {"title": "Test"}

    def test_nested_json(self):
        text = '{"outer": {"inner": 1}}'
        assert extract_json_object(text) == {"outer": {"inner": 1}}

    def test_strict_parse_accepts_a_bare_array(self):
        """The strict json.loads path accepts non-object JSON; callers type-check."""
        assert extract_json_object("[1, 2, 3]") == [1, 2, 3]

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json_object("this is not json at all")

    def test_empty_string_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json_object("")

    def test_no_closing_brace_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json_object('{"title": "Test"')

    def test_only_closing_brace_raises(self):
        """A closing brace before any opening brace is not recoverable."""
        with pytest.raises(json.JSONDecodeError):
            extract_json_object('} not json {')


class _TestClient(OpenAIChatMixin):
    """Concrete class to test the mixin."""

    def __init__(self, settings):
        self.settings = settings


class TestCreateCompletion:

    @pytest.fixture()
    def client(self):
        settings = MagicMock()
        settings.MAX_RETRIES = 3
        settings.MAX_RETRY_BACKOFF_SECONDS = 30
        return _TestClient(settings)

    @pytest.fixture(autouse=True)
    def _restore_holder(self):
        """Save and restore the holder's client after each test."""
        orig = _openai_holder._client
        yield
        _openai_holder._client = orig

    @patch("common.llm.llm_limiter")
    def test_delegates_to_openai(self, mock_limiter, client):
        """_create_completion passes kwargs through to the OpenAI client."""
        mock_openai = MagicMock()
        expected = MagicMock()
        mock_openai.chat.completions.create.return_value = expected
        _openai_holder.init(mock_openai)

        result = client._create_completion(
            model="gpt-5.4-mini",
            messages=[{"role": "user", "content": "hello"}],
        )

        assert result is expected
        mock_openai.chat.completions.create.assert_called_once_with(
            model="gpt-5.4-mini",
            messages=[{"role": "user", "content": "hello"}],
        )

    @patch("common.llm.llm_limiter")
    def test_uses_llm_limiter(self, mock_limiter, client):
        """_create_completion wraps the call in llm_limiter.acquire()."""
        mock_openai = MagicMock()
        _openai_holder.init(mock_openai)
        client._create_completion(model="m")

        mock_limiter.acquire.assert_called_once()

    @patch("common.llm.llm_limiter")
    def test_extra_kwargs_forwarded(self, mock_limiter, client):
        """All keyword arguments are forwarded to the OpenAI API."""
        mock_openai = MagicMock()
        _openai_holder.init(mock_openai)

        client._create_completion(
            model="gpt-5.4-mini",
            messages=[],
            temperature=0.5,
            max_tokens=100,
        )

        mock_openai.chat.completions.create.assert_called_once_with(
            model="gpt-5.4-mini",
            messages=[],
            temperature=0.5,
            max_tokens=100,
        )

    @patch("common.llm.llm_limiter")
    def test_raises_when_client_not_initialized(self, mock_limiter, client):
        """_create_completion raises RuntimeError when client is None."""
        _openai_holder._client = None
        with pytest.raises(RuntimeError, match="OpenAI client not initialised"):
            client._create_completion(model="m")



