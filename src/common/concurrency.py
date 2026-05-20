"""Semaphore-based concurrency guards for outbound API calls.

This module owns the single "0 means unbounded, otherwise cap with a bounded
semaphore" pattern, so neither the LLM wrapper nor the embedding client
hand-rolls it.

Two shapes are exported:

- :class:`ConcurrencyGuard` — a per-instance guard whose limit is known at
  construction. The embedding client (:mod:`common.embeddings`) constructs one
  directly from ``EMBEDDING_MAX_CONCURRENT``.
- ``llm_limiter`` — the module-global :class:`LLMConcurrencyLimiter` singleton
  used by every LLM call. Its limit is **not** known at import time, so it is
  initialised by :func:`common.bootstrap.bootstrap_daemon` via
  ``llm_limiter.init(max_concurrent)`` *after* ``setup_libraries`` and *before*
  preflight checks. Calling ``acquire()`` without a prior ``init()`` raises
  ``RuntimeError`` so a missing bootstrap step fails loud rather than silently
  degrading to unlimited concurrency.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

import structlog

log = structlog.get_logger(__name__)


class ConcurrencyGuard:
    """A reusable "at most N concurrent" guard, or unbounded when N is 0.

    The limit is fixed at construction. ``acquire()`` is a context manager: it
    blocks until a slot is free, yields, and releases the slot on exit — even
    when the guarded block raises.

    A non-positive *max_concurrent* means unbounded: ``acquire()`` becomes a
    zero-cost passthrough and no semaphore is allocated.
    """

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent > 0:
            self._semaphore: threading.BoundedSemaphore | None = (
                threading.BoundedSemaphore(max_concurrent)
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
    """The deferred-init concurrency guard for LLM API calls.

    Wraps a :class:`ConcurrencyGuard` whose limit is supplied later, at daemon
    bootstrap, rather than at import time. Until :meth:`init` is called,
    :meth:`acquire` raises ``RuntimeError``.
    """

    def __init__(self) -> None:
        self._guard: ConcurrencyGuard | None = None

    @property
    def _semaphore(self) -> threading.BoundedSemaphore | None:
        """The underlying semaphore, or ``None`` when unbounded or uninitialised.

        Exposed for tests that assert on the guard's internal state.
        """
        return self._guard._semaphore if self._guard is not None else None

    def init(self, max_concurrent: int) -> None:
        """Set the concurrency limit. ``0`` (or negative) means unlimited."""
        self._guard = ConcurrencyGuard(max_concurrent)
        if max_concurrent > 0:
            log.info("LLM concurrency limiter enabled", max_concurrent=max_concurrent)

    @contextmanager
    def acquire(self) -> Generator[None, None, None]:
        """Acquire a slot; no-op when unlimited.

        Raises ``RuntimeError`` if :meth:`init` was never called, so that
        a missing bootstrap step surfaces immediately rather than silently
        degrading to unlimited concurrency.
        """
        if self._guard is None:
            raise RuntimeError(
                "LLMConcurrencyLimiter.acquire() called before init(); "
                "ensure bootstrap_daemon() runs first"
            )
        with self._guard.acquire():
            yield


llm_limiter = LLMConcurrencyLimiter()
