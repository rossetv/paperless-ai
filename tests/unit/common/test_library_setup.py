"""Tests for common.library_setup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

import common.library_setup as library_setup
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


@pytest.fixture(autouse=True)
def _reset_library_setup_module_state():
    """Reset the module-level httpx-client / atexit holders after each test.

    setup_libraries keeps a single active httpx client and a single atexit
    registration across the process. The hot-reload tests assert on both, so
    each test starts with a clean slate.
    """
    saved_client = library_setup._active_http_client
    saved_atexit = library_setup._atexit_registered
    library_setup._active_http_client = None
    library_setup._atexit_registered = False
    yield
    library_setup._active_http_client = saved_client
    library_setup._atexit_registered = saved_atexit


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
    def test_httpx_client_created_and_registered_once(
        self, mock_register, mock_client_cls, mock_openai_cls
    ):
        mock_http = MagicMock()
        mock_client_cls.return_value = mock_http
        settings = _make_settings()
        setup_libraries(settings)
        mock_client_cls.assert_called_once_with(trust_env=False)
        assert mock_openai_cls.call_args.kwargs["http_client"] is mock_http
        # The atexit callback is the module's _close_active_http_client
        # function (NOT the client's .close directly) — so it always closes
        # the currently active client, never a stale one a hot-reload
        # replaced.
        mock_register.assert_called_once_with(library_setup._close_active_http_client)

    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.httpx.Client")
    @patch("common.library_setup.atexit.register")
    def test_hot_reload_closes_the_previous_client_and_replaces_it(
        self, mock_register, mock_client_cls, mock_openai_cls
    ):
        """A second setup_libraries call closes the previous httpx client
        and points the holder at the new one.

        Regression for the leak: every hot-reload used to leave the prior
        httpx.Client + atexit entry alive, so a long-running daemon with
        frequent config changes accumulated stranded clients indefinitely.
        """
        first_http = MagicMock(name="first_httpx_client")
        second_http = MagicMock(name="second_httpx_client")
        mock_client_cls.side_effect = [first_http, second_http]

        settings = _make_settings()
        setup_libraries(settings)
        setup_libraries(settings)

        # The first client was closed before the second was installed.
        first_http.close.assert_called_once()
        # The second is the currently active one.
        assert library_setup._active_http_client is second_http
        # atexit is only registered ONCE for the lifetime of the process.
        mock_register.assert_called_once()

    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.httpx.Client")
    @patch("common.library_setup.atexit.register")
    def test_atexit_callback_closes_the_currently_active_client(
        self, mock_register, mock_client_cls, mock_openai_cls
    ):
        """The single atexit callback routes through the active holder, so
        even after a hot-reload it closes the *current* client."""
        first_http = MagicMock(name="first_httpx_client")
        second_http = MagicMock(name="second_httpx_client")
        mock_client_cls.side_effect = [first_http, second_http]

        settings = _make_settings()
        setup_libraries(settings)
        setup_libraries(settings)

        # Simulate process exit: invoke the registered atexit callback. It
        # must close whichever client is active *now*, not the original one.
        callback = mock_register.call_args.args[0]
        callback()
        second_http.close.assert_called_once()
