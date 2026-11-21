"""Retry decorator with exponential backoff and jitter."""

from __future__ import annotations

import random
import time
from functools import wraps
from typing import Any, Callable, TypeVar

import structlog

log = structlog.get_logger(__name__)
T = TypeVar("T")


def retry(
    retryable_exceptions: tuple[type[Exception], ...],
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry an instance method on transient exceptions.

    The decorated method's owner must expose a ``settings`` attribute with
    ``MAX_RETRIES: int`` and ``MAX_RETRY_BACKOFF_SECONDS: int``.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self: Any, *args: object, **kwargs: object) -> T:
            settings = self.settings
            if settings.MAX_RETRIES < 1:
                raise ValueError("MAX_RETRIES must be >= 1")

            # The final attempt runs outside the loop so its exception propagates.
            for attempt in range(1, settings.MAX_RETRIES):
                try:
                    return func(self, *args, **kwargs)
                except retryable_exceptions as exc:
                    log.warning(
                        "retry.attempt_failed",
                        func_name=func.__name__,
                        error=str(exc),
                        attempt=attempt,
                        max_retries=settings.MAX_RETRIES,
                    )
                    _sleep_backoff(attempt, settings)

            try:
                return func(self, *args, **kwargs)
            except retryable_exceptions:
                log.exception(
                    "retry.exhausted",
                    func_name=func.__name__,
                    attempt=settings.MAX_RETRIES,
                )
                raise

        return wrapper

    return decorator


def _sleep_backoff(attempt: int, settings: Any) -> None:
    delay = (2**attempt) * random.uniform(0.8, 1.2)
    delay = min(delay, settings.MAX_RETRY_BACKOFF_SECONDS)
    time.sleep(delay)
