"""Process-wide graceful-shutdown flag, set by SIGTERM/SIGINT."""

from __future__ import annotations

import signal
import threading
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from types import FrameType

log = structlog.get_logger(__name__)

_shutdown_event = threading.Event()


def request_shutdown() -> None:
    _shutdown_event.set()


def is_shutdown_requested() -> bool:
    return _shutdown_event.is_set()


def wait_for_shutdown(timeout: float) -> None:
    """Sleep up to *timeout* seconds, returning at once if shutdown is requested."""
    _shutdown_event.wait(timeout)


def reset_shutdown() -> None:
    """Clear the shutdown flag; tests that set it must call this in teardown."""
    _shutdown_event.clear()


def register_signal_handlers() -> None:
    """Install SIGTERM/SIGINT handlers. Must be called from the main thread."""

    def _handler(signum: int, _frame: FrameType | None) -> None:
        name = signal.Signals(signum).name
        log.info("Received signal; requesting graceful shutdown", signal=name)
        request_shutdown()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
