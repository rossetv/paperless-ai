"""Tests for common.library_setup (per-provider chat client registry)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

import common.library_setup as library_setup
from common.library_setup import setup_libraries


def _make_settings(
    api_key: str = "sk-test",
    base_url: str | None = None,
) -> MagicMock:
    """A settings stub. setup_libraries reads only OPENAI_API_KEY (any step on
    openai → built), OLLAMA_BASE_URL (any step on ollama → built), and
    REQUEST_TIMEOUT — not LLM_PROVIDER, which is now just a per-step seed."""
    s = MagicMock()
    s.OPENAI_API_KEY = api_key
    s.OLLAMA_BASE_URL = base_url
    s.REQUEST_TIMEOUT = 180
    return s


@pytest.fixture(autouse=True)
def _reset_client_registry():
    """Reset the module-level per-provider client registry after each test."""
    import common.llm as llm_mod

    orig = dict(llm_mod._openai_holder._clients)
    yield
    llm_mod._openai_holder._clients = dict(orig)


@pytest.fixture(autouse=True)
def _reset_library_setup_module_state():
    """Reset the active-httpx-clients list and the atexit flag after each test.

    setup_libraries keeps one active httpx client per built provider and a single
    atexit registration across the process. The hot-reload tests assert on both,
    so each test starts with a clean slate.
    """
    saved_clients = library_setup._active_http_clients
    saved_atexit = library_setup._atexit_registered
    library_setup._active_http_clients = []
    library_setup._atexit_registered = False
    yield
    library_setup._active_http_clients = saved_clients
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
    def test_openai_client_built_when_key_configured(
        self, mock_register, mock_openai_cls
    ):
        import common.llm as llm_mod

        settings = _make_settings(api_key="sk-my-key", base_url=None)
        setup_libraries(settings)

        call_kwargs = mock_openai_cls.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-my-key"
        assert call_kwargs["base_url"] is None
        # Every chat call is bounded by REQUEST_TIMEOUT so a stalled provider
        # cannot hang a search for the SDK's ~600s default × retries.
        assert call_kwargs["timeout"] == 180
        assert llm_mod._openai_holder.is_ready("openai")
        # No Ollama connection → that slot stays empty.
        assert not llm_mod._openai_holder.is_ready("ollama")

    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.atexit.register")
    def test_openai_slot_cleared_when_no_key(self, mock_register, mock_openai_cls):
        import common.llm as llm_mod

        # Pre-seed the openai slot, then a fully-local reconfigure must clear it.
        llm_mod._openai_holder.init("openai", MagicMock())
        settings = _make_settings(api_key="", base_url="http://ollama:11434/v1/")
        setup_libraries(settings)
        assert not llm_mod._openai_holder.is_ready("openai")


class TestOllamaProvider:
    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.atexit.register")
    def test_ollama_client_built_when_base_url_configured(
        self, mock_register, mock_openai_cls
    ):
        import common.llm as llm_mod

        # api_key="" so only the Ollama slot is built → call_args is the Ollama call.
        settings = _make_settings(api_key="", base_url="http://ollama:11434/v1/")
        setup_libraries(settings)

        call_kwargs = mock_openai_cls.call_args.kwargs
        assert call_kwargs["base_url"] == "http://ollama:11434/v1/"
        assert call_kwargs["api_key"] == "dummy"
        assert llm_mod._openai_holder.is_ready("ollama")
        assert not llm_mod._openai_holder.is_ready("openai")


class TestBothProviders:
    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.httpx.Client")
    @patch("common.library_setup.atexit.register")
    def test_both_clients_built_when_both_connections_configured(
        self, mock_register, mock_client_cls, mock_openai_cls
    ):
        """A mixed deployment (some steps OpenAI, some Ollama) builds both slots
        and tracks both httpx clients."""
        import common.llm as llm_mod

        mock_client_cls.side_effect = [MagicMock(name="openai_http"), MagicMock(name="ollama_http")]
        settings = _make_settings(api_key="sk-x", base_url="http://ollama:11434/v1/")
        setup_libraries(settings)

        assert llm_mod._openai_holder.is_ready("openai")
        assert llm_mod._openai_holder.is_ready("ollama")
        assert mock_openai_cls.call_count == 2
        assert len(library_setup._active_http_clients) == 2


class TestHttpxClientAndCleanup:
    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.httpx.Client")
    @patch("common.library_setup.atexit.register")
    def test_httpx_client_created_and_registered_once(
        self, mock_register, mock_client_cls, mock_openai_cls
    ):
        mock_http = MagicMock()
        mock_client_cls.return_value = mock_http
        settings = _make_settings()  # openai-only
        setup_libraries(settings)
        mock_client_cls.assert_called_once_with(trust_env=False)
        assert mock_openai_cls.call_args.kwargs["http_client"] is mock_http
        # The atexit callback is the module's _close_active_http_clients function
        # (NOT a client's .close directly) — so it always closes whichever
        # clients are active, never stale ones a hot-reload replaced.
        mock_register.assert_called_once_with(library_setup._close_active_http_clients)

    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.httpx.Client")
    @patch("common.library_setup.atexit.register")
    def test_hot_reload_closes_the_previous_clients_and_replaces_them(
        self, mock_register, mock_client_cls, mock_openai_cls
    ):
        """A second setup_libraries call closes the previous httpx client(s) and
        installs the new one(s). Regression for the per-reload client leak."""
        first_http = MagicMock(name="first_httpx_client")
        second_http = MagicMock(name="second_httpx_client")
        mock_client_cls.side_effect = [first_http, second_http]

        settings = _make_settings()  # openai-only → one client per call
        setup_libraries(settings)
        setup_libraries(settings)

        first_http.close.assert_called_once()
        assert library_setup._active_http_clients == [second_http]
        # atexit is only registered ONCE for the lifetime of the process.
        mock_register.assert_called_once()

    @patch("common.library_setup.openai.OpenAI")
    @patch("common.library_setup.httpx.Client")
    @patch("common.library_setup.atexit.register")
    def test_atexit_callback_closes_the_currently_active_clients(
        self, mock_register, mock_client_cls, mock_openai_cls
    ):
        """The single atexit callback routes through the active list, so even
        after a hot-reload it closes the *current* clients."""
        first_http = MagicMock(name="first_httpx_client")
        second_http = MagicMock(name="second_httpx_client")
        mock_client_cls.side_effect = [first_http, second_http]

        settings = _make_settings()
        setup_libraries(settings)
        setup_libraries(settings)

        # Simulate process exit: invoke the registered atexit callback. It must
        # close whichever client is active *now*, not the original one.
        callback = mock_register.call_args.args[0]
        callback()
        second_http.close.assert_called_once()
