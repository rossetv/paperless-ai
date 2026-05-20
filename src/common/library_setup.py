"""One-shot third-party library configuration (OpenAI SDK, Pillow, httpx).

Builds the shared :mod:`common.llm` OpenAI client singleton used for **LLM
(chat-completion)** calls. That client follows ``LLM_PROVIDER`` — it points at
either OpenAI or the configured Ollama URL. Embeddings do **not** use this
singleton: :class:`~common.embeddings.EmbeddingClient` builds its own
OpenAI-pinned client, because embeddings always go to OpenAI regardless of
``LLM_PROVIDER`` (CODE_GUIDELINES §10.8, §15.4).
"""

from __future__ import annotations

import atexit
from typing import TYPE_CHECKING

import httpx
import openai
from PIL import Image

from .llm import init_openai_client

if TYPE_CHECKING:
    from .config import Settings


def setup_libraries(settings: Settings) -> None:
    """Configure Pillow and build the shared LLM OpenAI client singleton.

    Runs once per process during :func:`common.bootstrap.bootstrap_daemon`.
    The LLM client is provider-aware: under ``LLM_PROVIDER=ollama`` it points
    at ``OLLAMA_BASE_URL`` with a dummy key (Ollama ignores it); otherwise it
    uses ``OPENAI_API_KEY`` against OpenAI's default endpoint.
    """
    # Allow arbitrarily large images (high-DPI document scans).
    Image.MAX_IMAGE_PIXELS = None

    # OpenAI's SDK uses httpx internally.  In container environments it is
    # common to have proxy env-vars set unintentionally; explicitly opting
    # out of environment-based trust avoids surprising behaviour.
    http_client = httpx.Client(trust_env=False)
    atexit.register(http_client.close)

    if settings.LLM_PROVIDER == "ollama":
        # Ollama's OpenAI-compatible endpoint ignores the key, but the SDK
        # requires a non-empty string.
        api_key = "dummy"
        base_url = settings.OLLAMA_BASE_URL
    else:
        # OPENAI_API_KEY is a required, non-optional Settings field, so no
        # None-guard is needed here.
        api_key = settings.OPENAI_API_KEY
        base_url = None

    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
    )
    init_openai_client(client)
