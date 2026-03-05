"""Shared LLM helpers: retried chat completion, model dedup, thread-safe stats."""

from __future__ import annotations

import threading
from collections.abc import Iterable

import openai

from .concurrency import llm_limiter
from .retry import retry

RETRYABLE_OPENAI_EXCEPTIONS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class _OpenAIClientHolder:
    """Thread-safe holder for the shared OpenAI client singleton.

    Avoids a bare module-level mutable by encapsulating the state in an
    instance attribute with explicit init/get methods.
    """

    def __init__(self) -> None:
        self._client: openai.OpenAI | None = None

    def init(self, client: openai.OpenAI) -> None:
        self._client = client

    def get(self) -> openai.OpenAI:
        """Return the stored client, raising if not yet initialised."""
        if self._client is None:
            raise RuntimeError("OpenAI client not initialised; call setup_libraries() first")
        return self._client


_openai_holder = _OpenAIClientHolder()


def init_openai_client(client: openai.OpenAI) -> None:
    _openai_holder.init(client)


class OpenAIChatMixin:
    """
    Mixin providing a retried OpenAI-compatible chat completion call.

    The mixin expects ``self.settings`` to expose ``MAX_RETRIES`` and
    ``MAX_RETRY_BACKOFF_SECONDS`` for the retry decorator.
    """

    @retry(retryable_exceptions=RETRYABLE_OPENAI_EXCEPTIONS)
    def _create_completion(self, **kwargs):
        client = _openai_holder.get()
        with llm_limiter.acquire():
            return client.chat.completions.create(**kwargs)


def unique_models(models: list[str]) -> list[str]:
    """Deduplicate a model list while preserving insertion order."""
    return list(dict.fromkeys(models))


class ThreadSafeStats:
    """Thread-safe counter dict used by OCR and classification providers."""

    def __init__(self, keys: Iterable[str]) -> None:
        self._lock = threading.Lock()
        self._stats = {k: 0 for k in keys}

    def inc(self, key: str) -> None:
        with self._lock:
            self._stats[key] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def reset(self, keys: Iterable[str]) -> None:
        with self._lock:
            self._stats = {k: 0 for k in keys}
