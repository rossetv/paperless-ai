"""Retry decorator with exponential backoff and jitter."""

from __future__ import annotations

import random
import time
from functools import wraps
from typing import Callable, Protocol, TypeVar

import structlog

log = structlog.get_logger(__name__)
T = TypeVar("T")


class RetrySettings(Protocol):
    """The settings attributes required by the retry decorator."""

    MAX_RETRIES: int
    MAX_RETRY_BACKOFF_SECONDS: int


class HasRetrySettings(Protocol):
    """Protocol for classes whose methods can be decorated with ``@retry``.

    Any class using the ``@retry`` decorator must expose a ``settings``
    attribute that satisfies :class:`RetrySettings`.  This protocol makes
    that implicit contract explicit for static type checkers.
    """

    settings: RetrySettings


def retry(
    retryable_exceptions: tuple[type[Exception], ...],
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry an instance method on transient exceptions.

    The decorated method's owner must have a ``settings`` attribute
    satisfying :class:`RetrySettings`.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self: HasRetrySettings, *args: object, **kwargs: object) -> T:
            settings: RetrySettings = self.settings
            if settings.MAX_RETRIES < 1:
                raise ValueError("MAX_RETRIES must be >= 1")

            # Attempts 1 .. MAX_RETRIES-1 retry on a retryable failure; the
            # final attempt is made outside the loop so its result — a return
            # value or a propagated exception — is the function's outcome.
            # There is therefore no unreachable fall-through branch.
            for attempt in range(1, settings.MAX_RETRIES):
                try:
                    return func(self, *args, **kwargs)
                except retryable_exceptions as exc:
                    log.warning(
                        "Function failed, retrying",
                        func_name=func.__name__,
                        error=str(exc),
                        attempt=attempt,
                        max_retries=settings.MAX_RETRIES,
                    )
                    _sleep_backoff(attempt, settings)

            # Final attempt: a retryable failure here is logged with its
            # traceback and re-raised; a non-retryable failure propagates
            # untouched; success returns.
            try:
                return func(self, *args, **kwargs)
            except retryable_exceptions:
                log.exception(
                    "Function failed after all retries",
                    func_name=func.__name__,
                    attempt=settings.MAX_RETRIES,
                )
                raise

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
