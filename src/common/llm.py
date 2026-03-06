"""Shared LLM helpers: retried chat completion, model dedup, thread-safe stats.

Module-global singletons
~~~~~~~~~~~~~~~~~~~~~~~~
``_openai_holder`` stores the shared :class:`openai.OpenAI` client.  It is
initialised by :func:`common.library_setup.setup_libraries` during
:func:`common.bootstrap.bootstrap_daemon`.  Calling :func:`get_openai_client`
before initialisation raises ``RuntimeError``.

Boot order: Settings -> logging -> ``setup_libraries`` (inits ``_openai_holder``)
-> signal handlers -> ``llm_limiter.init`` (see :mod:`common.concurrency`).
See :func:`common.bootstrap.bootstrap_daemon` for the canonical sequence.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

import openai
from openai.types.chat import ChatCompletion

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

    def is_ready(self) -> bool:
        return self._client is not None

    def get(self) -> openai.OpenAI:
        if self._client is None:
            raise RuntimeError("OpenAI client not initialised; call setup_libraries() first")
        return self._client


_openai_holder = _OpenAIClientHolder()


def init_openai_client(client: openai.OpenAI) -> None:
    _openai_holder.init(client)


def get_openai_client() -> openai.OpenAI:
    return _openai_holder.get()


def is_openai_client_ready() -> bool:
    return _openai_holder.is_ready()


class OpenAIChatMixin:
    """
    Mixin providing a retried OpenAI-compatible chat completion call and
    thread-safe stats helpers.

    Subclasses define a ``_STAT_KEYS`` class attribute and call
    ``_init_stats()`` in their ``__init__``.  The mixin then provides
    ``reset_stats()`` and ``get_stats()``.

    The mixin expects ``self.settings`` to expose ``MAX_RETRIES`` and
    ``MAX_RETRY_BACKOFF_SECONDS`` for the retry decorator.
    """

    _STAT_KEYS: tuple[str, ...] = ()

    def _init_stats(self) -> None:
        self._stats = ThreadSafeStats(self._STAT_KEYS)

    def reset_stats(self) -> None:
        self._stats.reset(self._STAT_KEYS)

    def get_stats(self) -> dict[str, int]:
        return self._stats.snapshot()

    @retry(retryable_exceptions=RETRYABLE_OPENAI_EXCEPTIONS)
    def _create_completion(self, **kwargs: object) -> ChatCompletion:
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
