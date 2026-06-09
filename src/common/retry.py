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
        # rationale: `self` is any provider whose `settings` carries MAX_RETRIES /
        # MAX_RETRY_BACKOFF_SECONDS; the @retry contract is structural (duck-typed),
        # so Any is correct here — a Protocol would add a nominal layer nothing relies on.
        @wraps(func)
        def wrapper(self: Any, *args: object, **kwargs: object) -> T:
            settings = self.settings
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


# rationale: `settings` is any provider's structural settings object, read here for
# MAX_RETRY_BACKOFF_SECONDS / MAX_RETRIES; duck-typed, not a Protocol.
def _sleep_backoff(attempt: int, settings: Any) -> None:
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
