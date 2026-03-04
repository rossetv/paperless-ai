"""
LLM Concurrency Limiter
========================

Provides a global semaphore that caps the number of concurrent LLM API calls
across all worker threads.  This is especially useful for self-hosted Ollama
deployments where the GPU is the bottleneck.

Typical usage::

    from common.concurrency import init_llm_semaphore, llm_semaphore

    init_llm_semaphore(4)          # once at startup

    with llm_semaphore():          # in any worker thread
        openai.chat.completions.create(...)
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

import structlog

log = structlog.get_logger(__name__)

_semaphore: threading.Semaphore | None = None


def init_llm_semaphore(max_concurrent: int) -> None:
    """Initialize the global LLM concurrency semaphore.

    Args:
        max_concurrent: Maximum concurrent LLM calls.  ``0`` means unlimited.
    """
    global _semaphore
    if max_concurrent > 0:
        _semaphore = threading.BoundedSemaphore(max_concurrent)
        log.info("LLM concurrency limiter enabled", max_concurrent=max_concurrent)
    else:
        _semaphore = None


@contextmanager
def llm_semaphore() -> Generator[None, None, None]:
    """Context manager that acquires the LLM concurrency semaphore.

    When ``LLM_MAX_CONCURRENT`` is ``0`` (unlimited), this is a no-op.
    """
    if _semaphore is not None:
        _semaphore.acquire()
        try:
            yield
        finally:
            _semaphore.release()
    else:
        yield
