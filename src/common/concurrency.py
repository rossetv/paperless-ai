"""Semaphore-based concurrency limiter for LLM API calls.

The module-global ``llm_limiter`` singleton **must** be initialised by
calling ``llm_limiter.init(max_concurrent)`` before any ``acquire()``
call.  This is done inside :func:`common.bootstrap.bootstrap_daemon`
*after* ``setup_libraries`` and *before* preflight checks.  Calling
``acquire()`` without prior ``init()`` raises ``RuntimeError``.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

import structlog

log = structlog.get_logger(__name__)


class LLMConcurrencyLimiter:

    def __init__(self) -> None:
        self._semaphore: threading.Semaphore | None = None
        self._initialized: bool = False

    def init(self, max_concurrent: int) -> None:
        """Set the concurrency limit. ``0`` means unlimited."""
        if max_concurrent > 0:
            self._semaphore = threading.BoundedSemaphore(max_concurrent)
            log.info("LLM concurrency limiter enabled", max_concurrent=max_concurrent)
        else:
            self._semaphore = None
        self._initialized = True

    @contextmanager
    def acquire(self) -> Generator[None, None, None]:
        """Acquire a slot; no-op when unlimited.

        Raises ``RuntimeError`` if :meth:`init` was never called, so that
        a missing bootstrap step surfaces immediately rather than silently
        degrading to unlimited concurrency.
        """
        if not self._initialized:
            raise RuntimeError(
                "LLMConcurrencyLimiter.acquire() called before init(); "
                "ensure bootstrap_daemon() runs first"
            )
        if self._semaphore is not None:
            self._semaphore.acquire()
            try:
                yield
            finally:
                self._semaphore.release()
        else:
            yield


llm_limiter = LLMConcurrencyLimiter()
