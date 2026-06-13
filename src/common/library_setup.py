"""One-shot third-party library configuration (OpenAI SDK, Pillow, httpx).

Builds the :mod:`common.llm` per-provider chat-client registry used for **LLM
(chat-completion)** calls. Per-step provider selection means up to two clients
live at once: an **OpenAI** client (built when ``OPENAI_API_KEY`` is configured)
and an **Ollama** client (built when ``OLLAMA_BASE_URL`` is configured). Each AI
step routes to its slot via ``OpenAIChatMixin._provider`` → ``settings.*_PROVIDER``.
Embeddings do **not** use these: :class:`~common.embeddings.EmbeddingClient`
builds its own client from ``EMBEDDING_PROVIDER`` (CODE_GUIDELINES §10.8, §15.4).

This module is safe to call repeatedly — every daemon and the search server
re-run :func:`setup_libraries` on a hot-reload (web-redesign §5, Wave 4). The
previous httpx clients are closed before new ones are built, and a single
``atexit`` callback is registered exactly once and rewired to the active
clients, so an arbitrarily long-running process does not accumulate stranded
``httpx.Client`` instances or ``atexit`` entries.
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


# Module-level holder for the *currently active* httpx clients — one per built
# provider slot. Re-running setup_libraries closes the previous clients and
# installs the new ones, so a hot-reload never leaks an httpx connection pool or
# its TCP sockets (CODE_GUIDELINES §8 — I/O resource lifetimes).
_active_http_clients: list[httpx.Client] = []
_atexit_registered = False
# Serialises the close-then-replace pair so two concurrent re-init calls cannot
# lose a close. Process startup is single-threaded; this matters only on the
# hot-reload path the search server may take from its threadpool.
_setup_lock = threading.Lock()

# Ollama's OpenAI-compatible endpoint ignores the API key, but the SDK requires
# a non-empty string. Same sentinel and rationale as common.embeddings.
_OLLAMA_PLACEHOLDER_API_KEY = "dummy"


def _close_active_http_clients() -> None:
    """Close every currently active httpx client, if any.

    The single ``atexit`` callback (registered once on the first call to
    :func:`setup_libraries`) routes through this function — so even after a
    hot-reload it closes the *current* clients, never a dangling reference to
    the original startup ones.
    """
    global _active_http_clients
    clients = _active_http_clients
    _active_http_clients = []
    for client in clients:
        client.close()


def _build_provider_client(
    *, api_key: str, base_url: str | None, timeout: int
) -> tuple[openai.OpenAI, httpx.Client]:
    """Build one provider's chat client and its dedicated httpx client.

    OpenAI's SDK uses httpx internally; in containers a proxy env-var is often
    set unintentionally, so ``trust_env=False`` opts out of environment trust.
    ``timeout`` caps every chat call at REQUEST_TIMEOUT so a hung provider fails
    fast into the model-fallback/degrade path rather than blocking on the SDK's
    ~600s default and then being retried MAX_RETRIES times.
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

    Runs at startup via :func:`common.bootstrap.bootstrap_process`, and again on
    every config hot-reload. Per-step provider selection means up to two chat
    clients live at once: the **OpenAI** client is built whenever
    ``OPENAI_API_KEY`` is configured (any step on openai), and the **Ollama**
    client whenever ``OLLAMA_BASE_URL`` is configured (any step on ollama); a
    slot whose connection is absent is cleared. Each step routes to its slot via
    ``OpenAIChatMixin._provider`` → ``settings.*_PROVIDER``.

    Hot-reload safety: the previous httpx clients are closed before new ones are
    installed, and exactly one ``atexit`` callback is registered for the process
    lifetime — rewired to the active clients. A long-running daemon with frequent
    config changes therefore stays at one httpx client per live provider and one
    ``atexit`` entry, regardless of how many times this is called.
    """
    # Allow arbitrarily large images (high-DPI document scans).
    Image.MAX_IMAGE_PIXELS = None

    global _active_http_clients, _atexit_registered
    with _setup_lock:
        # Close the previous clients first so their connection pools / socket
        # FDs are released before the replacements are installed.
        _close_active_http_clients()

        if not _atexit_registered:
            # Register exactly once; the callback closes whichever clients are
            # active at process exit, not whichever we built on the first call.
            atexit.register(_close_active_http_clients)
            _atexit_registered = True

        new_http_clients: list[httpx.Client] = []

        # OpenAI slot — built when a key is configured (any step on openai),
        # against OpenAI's default endpoint. Cleared otherwise (all-local box).
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

        # Ollama slot — built when a base URL is configured (any step on ollama),
        # pointed at the OpenAI-compatible /v1/ endpoint. Cleared otherwise.
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
