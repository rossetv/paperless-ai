"""One-shot third-party library configuration (OpenAI SDK, Pillow, httpx).

Builds the shared :mod:`common.llm` OpenAI client singleton used for **LLM
(chat-completion)** calls. That client follows ``LLM_PROVIDER`` — it points at
either OpenAI or the configured Ollama URL. Embeddings do **not** use this
singleton: :class:`~common.embeddings.EmbeddingClient` builds its own
OpenAI-pinned client, because embeddings always go to OpenAI regardless of
``LLM_PROVIDER`` (CODE_GUIDELINES §10.8, §15.4).

This module is safe to call repeatedly — every daemon and the search server
re-run :func:`setup_libraries` on a hot-reload (web-redesign §5, Wave 4). The
previous httpx client is closed before a new one is built, and a single
``atexit`` callback is registered exactly once and rewired to the active
client, so an arbitrarily long-running process does not accumulate stranded
``httpx.Client`` instances or ``atexit`` entries.
"""

from __future__ import annotations

import atexit
import threading
from typing import TYPE_CHECKING

import httpx
import openai
from PIL import Image

from .llm import init_openai_client

if TYPE_CHECKING:
    from .config import Settings


# Module-level holders for the *currently active* httpx client. Re-running
# setup_libraries closes the previous client and points the singleton at the
# new one, so a hot-reload never leaks an httpx connection pool or its TCP
# sockets (CODE_GUIDELINES §8 — I/O resource lifetimes).
_active_http_client: httpx.Client | None = None
_atexit_registered = False
# Serialises the close-then-replace pair so two concurrent re-init calls
# cannot lose a close (race: A and B both read the same _active_http_client,
# both build new ones, and A's new client is dereferenced without being closed
# by B). Process startup is single-threaded; this matters only on the
# hot-reload path the search server may take from its threadpool.
_setup_lock = threading.Lock()


def _close_active_http_client() -> None:
    """Close the currently active httpx client, if any.

    The single ``atexit`` callback (registered once on the first call to
    :func:`setup_libraries`) routes through this function — so even after a
    hot-reload it closes the *current* client, never a dangling reference to
    the original startup one.
    """
    global _active_http_client
    client = _active_http_client
    if client is not None:
        _active_http_client = None
        client.close()


def setup_libraries(settings: Settings) -> None:
    """Configure Pillow and build the shared LLM OpenAI client singleton.

    Runs at startup via :func:`common.bootstrap.bootstrap_process`, and again
    on every config hot-reload — between daemon polls, and on a config-version
    change inside the search server's per-request core resolver. The LLM
    client is provider-aware: under ``LLM_PROVIDER=ollama`` it points at
    ``OLLAMA_BASE_URL`` with a dummy key (Ollama ignores it); otherwise it
    uses ``OPENAI_API_KEY`` against OpenAI's default endpoint.

    Hot-reload safety: the previous httpx client is closed before a new one
    is installed, and exactly one ``atexit`` callback is registered for the
    process lifetime — rewired to the active client. A long-running daemon
    with frequent config changes therefore stays at one httpx client and one
    ``atexit`` entry, regardless of how many times this is called.
    """
    # Allow arbitrarily large images (high-DPI document scans).
    Image.MAX_IMAGE_PIXELS = None

    global _active_http_client, _atexit_registered
    with _setup_lock:
        # Close the previous client first so its connection pool / socket
        # FDs are released before we install the replacement. The OpenAI
        # SDK wrapper around the old client becomes unreferenced as soon as
        # init_openai_client() points the holder at the new client; only
        # the httpx.Client itself is what we must close explicitly.
        _close_active_http_client()

        # OpenAI's SDK uses httpx internally.  In container environments it
        # is common to have proxy env-vars set unintentionally; explicitly
        # opting out of environment-based trust avoids surprising behaviour.
        http_client = httpx.Client(trust_env=False)
        _active_http_client = http_client
        if not _atexit_registered:
            # Register exactly once. The callback closes whichever client is
            # _active at process exit, not whichever client we happened to
            # build on the first call — that way a hot-reload does not leave
            # an orphaned atexit entry pinning a closed httpx.Client.
            atexit.register(_close_active_http_client)
            _atexit_registered = True

        if settings.LLM_PROVIDER == "ollama":
            # Ollama's OpenAI-compatible endpoint ignores the key, but the
            # SDK requires a non-empty string.
            api_key = "dummy"
            base_url = settings.OLLAMA_BASE_URL
        else:
            # OPENAI_API_KEY is a required, non-optional Settings field, so
            # no None-guard is needed here.
            api_key = settings.OPENAI_API_KEY
            base_url = None

        client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
        init_openai_client(client)
