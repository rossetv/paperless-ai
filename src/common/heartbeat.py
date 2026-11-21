"""Best-effort daemon heartbeat, written to ``daemon_status`` in ``app.db``.

A heartbeat write must never crash a daemon: sqlite and OS errors are logged and
swallowed. A daemon that stops beating reads as ``stopped``, which is also what
a crashed one looks like.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable

import structlog

from appdb import daemon_status

log = structlog.get_logger(__name__)

# A programming bug (e.g. TypeError) is deliberately not swallowed.
_HEARTBEAT_WRITE_EXCEPTIONS: tuple[type[Exception], ...] = (
    sqlite3.Error,
    OSError,
)


class Heartbeat:
    """A daemon's best-effort writer for its ``daemon_status`` row.

    The heartbeat does not own *conn*; the daemon opens and closes it.
    """

    def __init__(self, name: str, conn: sqlite3.Connection) -> None:
        self._name = name
        self._conn = conn
        # Held here so a failed write still accumulates; the next successful
        # beat reports the true running total.
        self._processed_count = 0

    @property
    def name(self) -> str:
        """The daemon name — ocr / classifier / indexer / search."""
        return self._name

    @property
    def processed_count(self) -> int:
        """The running total of work items this daemon has processed."""
        return self._processed_count

    def beat(self, *, detail: str, processed_delta: int = 0) -> None:
        """Record a heartbeat with a one-line *detail*; never raises.

        *processed_delta* is added to the running processed count.
        """
        self._processed_count += processed_delta
        try:
            daemon_status.record_heartbeat(
                self._conn,
                name=self._name,
                detail=detail,
                processed_count=self._processed_count,
            )
        except _HEARTBEAT_WRITE_EXCEPTIONS as exc:
            # No traceback: this is an expected, transient condition.
            log.warning(
                "heartbeat.write_failed",
                daemon=self._name,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    def touch(self, *, detail: str) -> None:
        """Refresh detail and freshness without touching the processed count.

        For a secondary writer such as the stall ticker, whose instance does not
        hold the real running total; ``beat`` would overwrite it with zero.
        """
        try:
            daemon_status.touch_heartbeat(self._conn, name=self._name, detail=detail)
        except _HEARTBEAT_WRITE_EXCEPTIONS as exc:
            log.warning(
                "heartbeat.write_failed",
                daemon=self._name,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    def beat_idle(self) -> None:
        """Record an idle heartbeat — the daemon has no work this cycle."""
        self.beat(detail=daemon_status.IDLE_DETAIL)


def run_heartbeat_ticker(
    heartbeat: Heartbeat,
    *,
    detail_fn: Callable[[], str],
    interval_seconds: int,
    should_stop: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Beat on a fixed interval until *should_stop* is True, then return.

    The heartbeat driver for a process with no work cycle (the search server).
    It beats before the first sleep so a new process shows up at once.
    *detail_fn* is called each tick so the detail can reflect live state.
    """
    interval = max(1, int(interval_seconds))
    while True:
        try:
            detail = detail_fn()
        except Exception:
            # A detail_fn bug must not crash the ticker.
            log.exception("heartbeat.detail_fn_failed", daemon=heartbeat.name)
            detail = "alive"
        heartbeat.beat(detail=detail)
        if should_stop():
            return
        sleep(interval)


# Comfortably inside the 90 s stale-after threshold, so a long in-cycle wait
# never flickers the daemon to "stopped".
DEFAULT_STALL_BEAT_INTERVAL_SECONDS: int = 30


def run_stall_ticker(
    heartbeat: Heartbeat,
    *,
    in_flight: threading.Event,
    stop: threading.Event,
    interval_seconds: int = DEFAULT_STALL_BEAT_INTERVAL_SECONDS,
    detail: str = "working — waiting on a slow upstream call",
) -> None:
    """Beat while a work cycle is stuck in flight; stay silent otherwise.

    The tag daemons beat after each poll returns, so a poll that blocks for
    hours (the flex capacity-429 wait) would make a live daemon read as
    stopped. This ticker fills that gap only while *in_flight* is set; a dead
    process still goes stale. It exits promptly when *stop* is set.

    *heartbeat* must use a connection owned by the ticker's thread: sqlite
    connections are not shared across threads.
    """
    interval = max(1, int(interval_seconds))
    while not stop.wait(interval):
        if in_flight.is_set():
            # touch, not beat: a beat would reset processed_count to zero.
            heartbeat.touch(detail=detail)
