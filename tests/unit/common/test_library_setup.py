"""Tests for common.library_setup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from common.library_setup import setup_libraries

def _make_settings(
    provider: str = "openai",
    api_key: str = "sk-test",
    base_url: str | None = None,
) -> MagicMock:
    s = MagicMock()
    s.LLM_PROVIDER = provider
    s.OPENAI_API_KEY = api_key
    s.OLLAMA_BASE_URL = base_url
    return s


@pytest.fixture(autouse=True)
def _reset_openai_client():
    """Reset the module-level OpenAI client holder after each test."""
    import common.llm as llm_mod
    orig = llm_mod._openai_holder._client
    yield
    llm_mod._openai_holder._client = orig

class TestPillowConfig:

    def test_max_image_pixels_set_to_none(self):
        settings = _make_settings()
        original = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = 12345  # non-None sentinel
            setup_libraries(settings)
            assert Image.MAX_IMAGE_PIXELS is None
        finally:
            Image.MAX_IMAGE_PIXELS = original

class TestOpenAIProvider:

    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.atexit.register")
    def test_openai_client_configured_correctly(self, mock_register, mock_openai_cls):
        import common.llm as llm_mod
        settings = _make_settings(provider="openai", api_key="sk-my-key")
        setup_libraries(settings)
        call_kwargs = mock_openai_cls.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-my-key"
        assert call_kwargs["base_url"] is None
        assert llm_mod._openai_holder._client is mock_openai_cls.return_value

class TestOllamaProvider:

    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.atexit.register")
    def test_ollama_client_configured_correctly(self, mock_register, mock_openai_cls):
        settings = _make_settings(
            provider="ollama",
            base_url="http://ollama:11434/v1/",
        )
        setup_libraries(settings)
        call_kwargs = mock_openai_cls.call_args.kwargs
        assert call_kwargs["base_url"] == "http://ollama:11434/v1/"
        assert call_kwargs["api_key"] == "dummy"

class TestHttpxClientAndCleanup:

    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.httpx.Client")
    @patch("common.library_setup.atexit.register")
    def test_httpx_client_created_and_registered(self, mock_register, mock_client_cls, mock_openai_cls):
        mock_http = MagicMock()
        mock_client_cls.return_value = mock_http
        settings = _make_settings()
        setup_libraries(settings)
        mock_client_cls.assert_called_once_with(trust_env=False)
        assert mock_openai_cls.call_args.kwargs["http_client"] is mock_http
        mock_register.assert_called_once_with(mock_http.close)
