"""
Generic retry decorator with exponential backoff and jitter.

This module provides a reusable :func:`retry` decorator that can be applied
to any instance method whose owning object exposes a ``settings`` attribute
conforming to the :class:`RetrySettings` protocol.  It is intentionally free
of business-logic imports so that it can be used by any module that needs
transient-error resilience (HTTP clients, LLM providers, etc.).

Backoff strategy
----------------
``delay = min(2^attempt * jitter, MAX_RETRY_BACKOFF_SECONDS)``

where *jitter* is drawn uniformly from ``[0.8, 1.2]`` to decorrelate
concurrent retriers.

Typical usage::

    from common.retry import retry

    class MyClient:
        def __init__(self, settings):
            self.settings = settings

        @retry(retryable_exceptions=(ConnectionError, TimeoutError))
        def fetch(self, url: str) -> bytes:
            ...
"""

from __future__ import annotations

import random
import time
from functools import wraps
from typing import Callable, Protocol, Type, TypeVar

import structlog

log = structlog.get_logger(__name__)
T = TypeVar("T")


class RetrySettings(Protocol):
    """Minimal interface required by the :func:`retry` decorator.

    Any object that exposes ``MAX_RETRIES`` and ``MAX_RETRY_BACKOFF_SECONDS``
    as integer attributes satisfies this protocol — no subclassing needed.
    """

    MAX_RETRIES: int
    MAX_RETRY_BACKOFF_SECONDS: int


def retry(
    retryable_exceptions: tuple[Type[Exception], ...],
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: retry an instance method on transient exceptions.

    The decorated method must belong to an object with a ``settings``
    attribute that satisfies :class:`RetrySettings`.

    Args:
        retryable_exceptions: Exception types that should trigger a retry.

    Returns:
        A decorator that wraps the target method with retry logic.

    Raises:
        ValueError: If ``settings.MAX_RETRIES < 1``.
        The original exception: After all retry attempts are exhausted.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self, *args, **kwargs) -> T:
            settings: RetrySettings = self.settings
            if settings.MAX_RETRIES < 1:
                raise ValueError("MAX_RETRIES must be >= 1")
            for attempt in range(1, settings.MAX_RETRIES + 1):
                try:
                    return func(self, *args, **kwargs)
                except retryable_exceptions as e:
                    if attempt == settings.MAX_RETRIES:
                        log.exception(
                            "Function failed after all retries",
                            func_name=func.__name__,
                            attempt=attempt,
                        )
                        raise
                    log.warning(
                        "Function failed, retrying",
                        func_name=func.__name__,
                        error=e,
                        attempt=attempt,
                        max_retries=settings.MAX_RETRIES,
                    )
                    _sleep_backoff(attempt, settings)

        return wrapper

    return decorator


def _sleep_backoff(attempt: int, settings: RetrySettings) -> None:
    """Sleep with exponential backoff, jitter, and a configurable cap.

    Args:
        attempt: The 1-based attempt number (used as the exponent).
        settings: Provides ``MAX_RETRY_BACKOFF_SECONDS`` as the delay ceiling.
    """
    delay = (2**attempt) * random.uniform(0.8, 1.2)
    delay = min(delay, settings.MAX_RETRY_BACKOFF_SECONDS)
    log.info(
        "Sleeping before retry",
        delay=f"{delay:.1f}s",
        attempt=attempt,
        max_retries=settings.MAX_RETRIES,
        max_backoff=settings.MAX_RETRY_BACKOFF_SECONDS,
    )
    time.sleep(delay)
