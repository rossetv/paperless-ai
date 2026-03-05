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

# Module-level OpenAI client, initialised by setup_libraries().
_openai_client: openai.OpenAI | None = None


def init_openai_client(client: openai.OpenAI) -> None:
    """Store the configured OpenAI client for use by the mixin."""
    global _openai_client  # noqa: PLW0603
    _openai_client = client


class OpenAIChatMixin:
    """
    Mixin providing a retried OpenAI-compatible chat completion call.

    The mixin expects ``self.settings`` to expose ``MAX_RETRIES`` and
    ``MAX_RETRY_BACKOFF_SECONDS`` for the retry decorator.
    """

    @retry(retryable_exceptions=RETRYABLE_OPENAI_EXCEPTIONS)
    def _create_completion(self, **kwargs):
        """Call the OpenAI-compatible chat completion API with retries."""
        if _openai_client is None:
            raise RuntimeError("OpenAI client not initialised; call setup_libraries() first")
        with llm_limiter.acquire():
            return _openai_client.chat.completions.create(**kwargs)


def unique_models(models: list[str]) -> list[str]:
    """Deduplicate a model list while preserving insertion order."""
    seen: set[str] = set()
    unique: list[str] = []
    for model in models:
        if model not in seen:
            seen.add(model)
            unique.append(model)
    return unique


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
