"""Semaphore-based concurrency guards for outbound API calls.

:class:`ConcurrencyGuard` takes its limit at construction. ``llm_limiter`` is
initialised at bootstrap via ``llm_limiter.init()``; ``acquire()`` before that
raises ``RuntimeError`` rather than silently running unbounded.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

import structlog

log = structlog.get_logger(__name__)


class ConcurrencyGuard:
    """An "at most N concurrent" guard; a non-positive N means unbounded."""

    def __init__(self, max_concurrent: int) -> None:
        self.max_concurrent = max(0, max_concurrent)
        if self.max_concurrent > 0:
            self._semaphore: threading.BoundedSemaphore | None = (
                threading.BoundedSemaphore(self.max_concurrent)
            )
        else:
            self._semaphore = None

    @contextmanager
    def acquire(self) -> Generator[None, None, None]:
        """Acquire a slot for the duration of the ``with`` block.

        A no-op (immediate yield) when the guard is unbounded.
        """
        if self._semaphore is None:
            yield
            return
        self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()


class LLMConcurrencyLimiter:
    """The concurrency guard for LLM API calls, sized at bootstrap via :meth:`init`."""

    def __init__(self) -> None:
        self._guard: ConcurrencyGuard | None = None

    @property
    def _semaphore(self) -> threading.BoundedSemaphore | None:
        """The underlying semaphore, or ``None``; exposed for tests."""
        return self._guard._semaphore if self._guard is not None else None

    def init(self, max_concurrent: int) -> None:
        """Set the concurrency limit. ``0`` (or negative) means unlimited.

        An unchanged limit keeps the existing guard. A changed one swaps in a new
        guard without waiting for old permits to drain, so in-flight calls may
        briefly push the total above the new limit.
        """
        if self._guard is not None and self._guard.max_concurrent == max_concurrent:
            return
        self._guard = ConcurrencyGuard(max_concurrent)
        if max_concurrent > 0:
            log.info("LLM concurrency limiter enabled", max_concurrent=max_concurrent)

    @contextmanager
    def acquire(self) -> Generator[None, None, None]:
        """Acquire a slot; no-op when unlimited. Raises if :meth:`init` never ran."""
        if self._guard is None:
            raise RuntimeError(
                "LLMConcurrencyLimiter.acquire() called before init(); "
                "ensure bootstrap_daemon() runs first"
            )
        with self._guard.acquire():
            yield


llm_limiter = LLMConcurrencyLimiter()
