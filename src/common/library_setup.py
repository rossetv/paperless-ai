"""One-shot third-party library configuration (OpenAI SDK, Pillow, httpx).

Builds the per-provider chat clients in :mod:`common.llm`; embeddings build
their own. Safe to re-run on every config hot-reload: previous httpx clients are
closed and one ``atexit`` hook is rewired, so nothing accumulates.
"""

from __future__ import annotations

import atexit
import threading
from typing import TYPE_CHECKING

import httpx
import openai
from PIL import Image

from .llm import set_chat_client

if TYPE_CHECKING:
    from .config import Settings

# Pillow's decompression-bomb cap: it warns above this many pixels and refuses
# to decode above twice it; the OCR image converter refuses above it. 250 MP clears every real document (A0 at 400 DPI
# is ~248 MP, large phone photos ~200 MP) while keeping Pillow's bomb checks —
# several of its CVE fixes rely on them — live for untrusted uploads.
_MAX_IMAGE_PIXELS = 250_000_000


# The currently active httpx clients, one per built provider slot.
_active_http_clients: list[httpx.Client] = []
_atexit_registered = False
# Serialises the close-then-replace pair so two concurrent re-init calls cannot
# lose a close. Process startup is single-threaded; this matters only on the
# hot-reload path the search server may take from its threadpool.
_setup_lock = threading.Lock()

# Ollama ignores the API key, but the SDK requires a non-empty string.
_OLLAMA_PLACEHOLDER_API_KEY = "dummy"


def _close_active_http_clients() -> None:
    """Close every currently active httpx client; also the ``atexit`` hook."""
    global _active_http_clients
    clients = _active_http_clients
    _active_http_clients = []
    for client in clients:
        client.close()


def _build_provider_client(
    *, api_key: str, base_url: str | None, timeout: int
) -> tuple[openai.OpenAI, httpx.Client]:
    """Build one provider's chat client and its dedicated httpx client.

    ``trust_env=False`` ignores proxy env vars, often set unintentionally in
    containers. The timeout makes a hung provider fail fast into the fallback
    path instead of blocking on the SDK's ~600 s default.
    """
    http_client = httpx.Client(trust_env=False)
    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        timeout=timeout,
    )
    return client, http_client


def setup_libraries(settings: Settings) -> None:
    """Configure Pillow and build the per-provider chat client registry.

    The OpenAI client is built when ``OPENAI_API_KEY`` is set and the Ollama
    client when ``OLLAMA_BASE_URL`` is set; a slot without its connection is
    cleared.
    """
    Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS

    global _active_http_clients, _atexit_registered
    with _setup_lock:
        _close_active_http_clients()

        if not _atexit_registered:
            atexit.register(_close_active_http_clients)
            _atexit_registered = True

        new_http_clients: list[httpx.Client] = []

        if settings.OPENAI_API_KEY:
            client, http_client = _build_provider_client(
                api_key=settings.OPENAI_API_KEY,
                base_url=None,
                timeout=settings.REQUEST_TIMEOUT,
            )
            set_chat_client("openai", client)
            new_http_clients.append(http_client)
        else:
            set_chat_client("openai", None)

        if settings.OLLAMA_BASE_URL:
            client, http_client = _build_provider_client(
                api_key=_OLLAMA_PLACEHOLDER_API_KEY,
                base_url=settings.OLLAMA_BASE_URL,
                timeout=settings.REQUEST_TIMEOUT,
            )
            set_chat_client("ollama", client)
            new_http_clients.append(http_client)
        else:
            set_chat_client("ollama", None)

        _active_http_clients = new_http_clients
