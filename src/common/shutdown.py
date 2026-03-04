"""
Graceful Shutdown Coordinator
=============================

Provides a thread-safe shutdown flag that signal handlers (SIGTERM, SIGINT)
can set, and that the daemon polling loop checks between iterations.

Typical usage::

    from common.shutdown import register_signal_handlers, is_shutdown_requested

    register_signal_handlers()   # once at startup
    while not is_shutdown_requested():
        ...
"""

from __future__ import annotations

import signal
import threading

import structlog

log = structlog.get_logger(__name__)

_shutdown_event = threading.Event()


def request_shutdown() -> None:
    """Signal that the daemon should stop after the current batch."""
    _shutdown_event.set()


def is_shutdown_requested() -> bool:
    """Return ``True`` when a graceful shutdown has been requested."""
    return _shutdown_event.is_set()


def reset_shutdown() -> None:
    """Clear the shutdown flag (useful for tests)."""
    _shutdown_event.clear()


def register_signal_handlers() -> None:
    """Install SIGTERM and SIGINT handlers that trigger a graceful shutdown.

    Must be called from the **main thread** (Python requires signal handlers
    to be registered there).
    """

    def _handler(signum: int, _frame) -> None:
        name = signal.Signals(signum).name
        log.info("Received signal; requesting graceful shutdown", signal=name)
        request_shutdown()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
