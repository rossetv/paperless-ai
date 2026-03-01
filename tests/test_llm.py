"""Tests for common.llm — shared LLM helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from common.llm import OpenAIChatMixin, unique_models


def test_unique_models_deduplicates():
    result = unique_models(["a", "b", "a", "c", "b"])
    assert result == ["a", "b", "c"]


def test_unique_models_preserves_order():
    result = unique_models(["c", "b", "a"])
    assert result == ["c", "b", "a"]


def test_unique_models_empty():
    assert unique_models([]) == []


def test_unique_models_single():
    assert unique_models(["model-a"]) == ["model-a"]


def test_create_completion_delegates_to_openai(mocker):
    """Line 31: _create_completion forwards kwargs to openai.chat.completions.create."""
    mock_create = mocker.patch("common.llm.openai.chat.completions.create")
    mock_response = MagicMock()
    mock_create.return_value = mock_response

    class TestClient(OpenAIChatMixin):
        def __init__(self):
            self.settings = SimpleNamespace(MAX_RETRIES=1, MAX_RETRY_BACKOFF_SECONDS=1)

    client = TestClient()
    result = client._create_completion(model="test-model", messages=[{"role": "user", "content": "hi"}])

    assert result is mock_response
    mock_create.assert_called_once_with(model="test-model", messages=[{"role": "user", "content": "hi"}])
