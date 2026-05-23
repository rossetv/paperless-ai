"""Best-effort daemon heartbeat — the daemon side of the Index dashboard.

Each of the four daemons (ocr, classifier, indexer, search) owns one
:class:`Heartbeat`, constructed at startup over an open ``app.db``
connection, and calls :meth:`Heartbeat.beat` on every work cycle. The beat
upserts the daemon's row in the ``daemon_status`` table (web-redesign spec
§5, Wave 6); the search server reads those rows to render the dashboard.

**The cardinal rule: a heartbeat write must never crash a daemon.** The
dashboard is observability — it is strictly less important than the daemon's
real job (OCR, classification, indexing, serving search). If ``app.db`` is
briefly locked, the file is missing, or the write raises any ``sqlite3`` or
OS error, :meth:`beat` logs at WARNING and returns. The daemon carries on.
A daemon that stops heartbeating is reported ``stopped`` by the reader's
staleness derivation — which is also exactly what a genuinely crashed daemon
looks like, so a swallowed write degrades the dashboard gracefully.

This is the single implementation of that guarantee; the four daemons share
it rather than each re-deriving the try/except.

``common`` is permitted to import ``appdb`` (see the package docstring);
this module and :mod:`common.config` are its only two importers.
"""

from __future__ import annotations

import sqlite3

import structlog

from appdb import daemon_status

log = structlog.get_logger(__name__)

# The sqlite3 and OS errors a best-effort heartbeat write swallows. A genuine
# programming bug (e.g. a TypeError from wrong arguments) is NOT in this set
# — it is not caught, so it still surfaces loudly in tests and review.
_HEARTBEAT_WRITE_EXCEPTIONS: tuple[type[Exception], ...] = (
    sqlite3.Error,
    OSError,
)


class Heartbeat:
    """A daemon's best-effort writer for its ``daemon_status`` row.

    Holds the daemon name, an open ``app.db`` connection, and the monotonic
    processed-count the daemon accumulates. One instance per daemon, built at
    startup and reused for the process lifetime.

    Args:
        name: The daemon name — ocr / classifier / indexer / search.
        conn: An open, migrated ``app.db`` connection. The heartbeat does not
            own the connection's lifecycle — the daemon opens and closes it.
    """

    def __init__(self, name: str, conn: sqlite3.Connection) -> None:
        self._name = name
        self._conn = conn
        # The daemon's monotonic throughput counter. Held here so a beat
        # whose DB write fails still accumulates — the next successful beat
        # then reports the true running total, not just that beat's delta.
        self._processed_count = 0

    @property
    def processed_count(self) -> int:
        """The running total of work items this daemon has processed."""
        return self._processed_count

    def beat(self, *, detail: str, processed_delta: int = 0) -> None:
        """Record a heartbeat — best-effort; never raises.

        Adds *processed_delta* to the running processed-count and upserts the
        daemon's ``daemon_status`` row. Any ``sqlite3`` or OS error is logged
        at WARNING and swallowed: the dashboard is not worth crashing a
        daemon over.

        Args:
            detail: A short human string describing the current activity —
                pass a real one-liner when working; use :meth:`beat_idle`
                (or ``detail="idle"``) when there is no work.
            processed_delta: How many work items were processed since the
                last beat. Added to the running total.
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
            # rationale: best-effort observability boundary — a heartbeat
            # write failure must never crash the daemon (web-redesign §5).
            # WARNING, not ERROR: the daemon's real work is unaffected; the
            # dashboard simply reports this daemon "stopped" until the next
            # successful beat. error=str(exc) is enough — no traceback noise
            # for an expected, transient condition.
            log.warning(
                "heartbeat.write_failed",
                daemon=self._name,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    def beat_idle(self) -> None:
        """Record an idle heartbeat — the daemon has no work this cycle.

        A convenience for the common ``beat(detail="idle")`` call. The
        reader maps a fresh ``idle`` heartbeat to the ``idle`` dashboard
        state. Best-effort, exactly like :meth:`beat`.
        """
        self.beat(detail=daemon_status.IDLE_DETAIL)
