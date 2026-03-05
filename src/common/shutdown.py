"""Thread-safe graceful shutdown flag for SIGTERM/SIGINT handling."""

from __future__ import annotations

import signal
import threading

import structlog

log = structlog.get_logger(__name__)

_shutdown_event = threading.Event()


def request_shutdown() -> None:
    _shutdown_event.set()


def is_shutdown_requested() -> bool:
    return _shutdown_event.is_set()


def reset_shutdown() -> None:
    _shutdown_event.clear()


def register_signal_handlers() -> None:
    """Install SIGTERM/SIGINT handlers. Must be called from the main thread."""

    def _handler(signum: int, _frame) -> None:
        name = signal.Signals(signum).name
        log.info("Received signal; requesting graceful shutdown", signal=name)
        request_shutdown()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
