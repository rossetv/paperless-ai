"""Retry decorator with exponential backoff and jitter."""

from __future__ import annotations

import random
import time
from functools import wraps
from typing import Callable, Protocol, Type, TypeVar

import structlog

log = structlog.get_logger(__name__)
T = TypeVar("T")


class RetrySettings(Protocol):
    MAX_RETRIES: int
    MAX_RETRY_BACKOFF_SECONDS: int


def retry(
    retryable_exceptions: tuple[Type[Exception], ...],
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry an instance method on transient exceptions.

    The decorated method's owner must have a ``settings`` attribute
    satisfying :class:`RetrySettings`.
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
