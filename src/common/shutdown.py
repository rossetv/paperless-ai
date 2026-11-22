"""Process-wide graceful-shutdown flag, set by SIGTERM/SIGINT."""

from __future__ import annotations

import signal
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from types import FrameType

log = structlog.get_logger(__name__)

# A plain flag, not a threading.Event: Event.set() takes a lock the main thread
# may hold while waiting, which would deadlock a signal handler running there.
_shutdown_requested = False

_WAIT_SLICE_SECONDS = 0.5


def request_shutdown() -> None:
    global _shutdown_requested
    _shutdown_requested = True


def is_shutdown_requested() -> bool:
    return _shutdown_requested


def wait_for_shutdown(timeout: float) -> None:
    """Sleep up to *timeout* seconds, returning within half a second of a shutdown request."""
    deadline = time.monotonic() + timeout
    while not _shutdown_requested:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(_WAIT_SLICE_SECONDS, remaining))


def reset_shutdown() -> None:
    """Clear the shutdown flag; tests that set it must call this in teardown."""
    global _shutdown_requested
    _shutdown_requested = False


def register_signal_handlers() -> None:
    """Install SIGTERM/SIGINT handlers. Must be called from the main thread."""

    def _handler(signum: int, _frame: FrameType | None) -> None:
        name = signal.Signals(signum).name
        log.info("Received signal; requesting graceful shutdown", signal=name)
        request_shutdown()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
