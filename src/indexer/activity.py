"""Reconcile-activity recording and heartbeat for the indexer daemon.

The Index dashboard (web-redesign spec §5, Wave 6) needs two things from the
indexer that live in ``app.db``: a daemon-status heartbeat, and a per-cycle
"Recent activity" log. :class:`IndexerActivityRecorder` owns both — the
indexer's reconciliation loop calls it after each incremental sync and each
deletion sweep.

Both writes are **best-effort**: a failure recording activity or beating the
heartbeat must never crash the indexer, whose real job is keeping the search
index correct. The :class:`~common.heartbeat.Heartbeat` already swallows its
write errors; this class wraps the ``reconcile_activity`` write the same way.

The ``ok`` flag on a recorded cycle means *the cycle completed*, not *every
document succeeded*: a sync with per-document failures still ran to
completion (the failures are isolated and retried — SPEC §5.7), so it is
``ok=True`` with the failure count in the summary. Only a sweep that
*aborted* — its Paperless enumeration failed — is ``ok=False``.

Allowed deps: appdb (daemon_status, reconcile_activity), common.heartbeat,
indexer.reconciler (the report dataclasses), structlog.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import structlog

from appdb import reconcile_activity
from common.heartbeat import Heartbeat

if TYPE_CHECKING:
    from indexer.reconciler import SyncReport
    from indexer.reconciler._sweep import SweepReport

log = structlog.get_logger(__name__)

# The name this daemon registers under in daemon_status.
_DAEMON_NAME = "indexer"

# Errors a best-effort reconcile_activity write swallows. A genuine bug
# (wrong arguments → TypeError) is not in this set and still surfaces.
_ACTIVITY_WRITE_EXCEPTIONS: tuple[type[Exception], ...] = (
    sqlite3.Error,
    OSError,
)


class IndexerActivityRecorder:
    """Records the indexer's reconcile cycles and beats its heartbeat.

    One instance is built at daemon startup over an open ``app.db``
    connection and passed into the reconciliation loop.

    Args:
        conn: An open, migrated ``app.db`` connection. The recorder does not
            own the connection's lifecycle — the daemon opens and closes it.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._heartbeat = Heartbeat(name=_DAEMON_NAME, conn=conn)

    def record_sync(
        self,
        report: SyncReport,
        *,
        started_at: str,
        finished_at: str,
    ) -> None:
        """Record one incremental-sync cycle and beat the heartbeat.

        The cycle is ``ok=True`` — an incremental sync that reaches its
        ``SyncReport`` has completed; per-document failures are counted in
        the summary, not treated as a cycle failure.

        Args:
            report: The cycle's :class:`~indexer.reconciler.SyncReport`.
            started_at: ISO-8601 UTC timestamp the cycle began.
            finished_at: ISO-8601 UTC timestamp the cycle ended.
        """
        summary = {
            "indexed": report.indexed,
            "metadata_only": report.metadata_only,
            "skipped": report.skipped,
            "failed": report.failed,
            "given_up": report.given_up,
        }
        detail = (
            f"indexed {report.indexed}, {report.failed} failed"
            if report.failed
            else f"indexed {report.indexed} document(s)"
        )
        self._record(
            kind="sync",
            started_at=started_at,
            finished_at=finished_at,
            ok=True,
            summary=summary,
            detail=detail,
        )
        self._heartbeat.beat(detail=detail)

    def record_sweep(
        self,
        report: SweepReport,
        *,
        started_at: str,
        finished_at: str,
    ) -> None:
        """Record one deletion-sweep cycle and beat the heartbeat.

        The cycle is ``ok=False`` only when the sweep *aborted* — its
        Paperless enumeration failed, so it pruned nothing (SPEC §5.4).

        Args:
            report: The cycle's :class:`~indexer.reconciler._sweep.SweepReport`.
            started_at: ISO-8601 UTC timestamp the cycle began.
            finished_at: ISO-8601 UTC timestamp the cycle ended.
        """
        summary = {
            "pruned": report.pruned,
            "aborted": 1 if report.aborted else 0,
            "candidates": report.candidates,
        }
        detail = (
            "sweep aborted: Paperless enumeration failed"
            if report.aborted
            else f"pruned {report.pruned} deleted document(s)"
        )
        self._record(
            kind="sweep",
            started_at=started_at,
            finished_at=finished_at,
            ok=not report.aborted,
            summary=summary,
            detail=detail,
        )
        self._heartbeat.beat(detail=detail)

    def record_rebuild(self, *, started_at: str, finished_at: str) -> None:
        """Record an index rebuild and beat the heartbeat.

        The rebuild itself only wipes the index; the full re-index happens in
        the incremental sync that immediately follows. The recorded row is
        ``kind="sync"`` (it precedes a sync) and ``ok=True``, with a detail
        string an operator will recognise in the dashboard's activity list.

        Args:
            started_at: ISO-8601 UTC timestamp the rebuild began.
            finished_at: ISO-8601 UTC timestamp the wipe finished.
        """
        detail = "index rebuilt — re-indexing the whole archive"
        self._record(
            kind="sync",
            started_at=started_at,
            finished_at=finished_at,
            ok=True,
            summary={"rebuilt": 1},
            detail=detail,
        )
        self._heartbeat.beat(detail=detail)

    def beat_idle(self) -> None:
        """Beat an idle indexer heartbeat — the loop is between cycles."""
        self._heartbeat.beat_idle()

    def _record(
        self,
        *,
        kind: str,
        started_at: str,
        finished_at: str,
        ok: bool,
        summary: dict[str, int],
        detail: str,
    ) -> None:
        """Append a reconcile_activity row — best-effort; never raises."""
        try:
            reconcile_activity.record_cycle(
                self._conn,
                kind=kind,  # type: ignore[arg-type]
                started_at=started_at,
                finished_at=finished_at,
                ok=ok,
                summary=summary,
                detail=detail,
            )
        except _ACTIVITY_WRITE_EXCEPTIONS as exc:
            # rationale: best-effort observability boundary — failing to log
            # a reconcile cycle must never crash the indexer (web-redesign
            # §5). WARNING: the index itself is unaffected; only the
            # dashboard's activity history misses this row.
            log.warning(
                "indexer.activity_write_failed",
                kind=kind,
                error=str(exc),
                error_type=type(exc).__name__,
            )
