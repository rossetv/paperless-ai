"""
Comprehensive tests for ``common.llm``.

Covers ``unique_models`` deduplication and ``OpenAIChatMixin._create_completion``
delegation and concurrency limiter usage.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from common.llm import OpenAIChatMixin, unique_models


# ===================================================================
# unique_models
# ===================================================================

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


# ===================================================================
# OpenAIChatMixin._create_completion
# ===================================================================

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

    @patch("common.llm.llm_limiter")
    @patch("common.llm._openai_client")
    def test_delegates_to_openai(self, mock_client, mock_limiter, client):
        """_create_completion passes kwargs through to the OpenAI client."""
        expected = MagicMock()
        mock_client.chat.completions.create.return_value = expected

        result = client._create_completion(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": "hello"}],
        )

        assert result is expected
        mock_client.chat.completions.create.assert_called_once_with(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": "hello"}],
        )

    @patch("common.llm.llm_limiter")
    @patch("common.llm._openai_client")
    def test_uses_llm_limiter(self, mock_client, mock_limiter, client):
        """_create_completion wraps the call in llm_limiter.acquire()."""
        mock_client.chat.completions.create.return_value = MagicMock()
        client._create_completion(model="m")

        mock_limiter.acquire.assert_called_once()

    @patch("common.llm.llm_limiter")
    @patch("common.llm._openai_client")
    def test_extra_kwargs_forwarded(self, mock_client, mock_limiter, client):
        """All keyword arguments are forwarded to the OpenAI API."""
        mock_client.chat.completions.create.return_value = MagicMock()

        client._create_completion(
            model="gpt-5-mini",
            messages=[],
            temperature=0.5,
            max_tokens=100,
        )

        mock_client.chat.completions.create.assert_called_once_with(
            model="gpt-5-mini",
            messages=[],
            temperature=0.5,
            max_tokens=100,
        )

    @patch("common.llm.llm_limiter")
    def test_raises_when_client_not_initialized(self, mock_limiter, client):
        """_create_completion raises RuntimeError when client is None."""
        with patch("common.llm._openai_client", None):
            with pytest.raises(RuntimeError, match="OpenAI client not initialised"):
                client._create_completion(model="m")
