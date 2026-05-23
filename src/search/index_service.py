"""Pure shaping logic for the Index operations dashboard (spec §5, Wave 6).

The Index route handlers (:mod:`search.index_routes`) are thin: they read
rows from ``appdb`` and the store, and call this module. This module has no
FastAPI, no I/O, no database — just two pure functions, so the dashboard's
rules are unit-testable in isolation.

- :func:`resolve_daemon_statuses` guarantees the dashboard always sees all
  four daemons. ``appdb.daemon_status`` only returns rows that exist; a
  daemon that has never run (a fresh install) or whose row was never created
  is absent. This function fills any absentee in as ``stopped`` — which is
  the truth: a process that has never heartbeated is not running.
- :func:`overall_health` rolls the four per-daemon states into the single
  health verdict the dashboard's hero shows.

Allowed deps: appdb.daemon_status. Forbidden: fastapi, sqlite3, store,
indexer, the daemon packages.
"""

from __future__ import annotations

from typing import Literal

from appdb.daemon_status import DaemonStatus

# The four daemon processes the dashboard always shows a tile for, sorted so
# the dashboard ordering is stable. resolve_daemon_statuses guarantees a
# status for every name here.
KNOWN_DAEMONS: tuple[str, ...] = ("classifier", "indexer", "ocr", "search")

# A heartbeat timestamp for a daemon that has never written one. It is in the
# distant past so any downstream staleness check also treats it as stale.
_NEVER = "1970-01-01T00:00:00+00:00"

#: The overall-health verdict the dashboard hero renders.
OverallHealth = Literal["ok", "degraded", "down"]


def resolve_daemon_statuses(
    rows: list[DaemonStatus],
) -> list[DaemonStatus]:
    """Return a status for all four known daemons, newest data preferred.

    Any daemon in :data:`KNOWN_DAEMONS` missing from *rows* — it has never
    written a heartbeat — is synthesised as ``stopped``. The result is
    ordered by :data:`KNOWN_DAEMONS`, so the dashboard's tile order is
    deterministic.

    Args:
        rows: The :class:`~appdb.daemon_status.DaemonStatus` rows
            ``appdb.daemon_status.read_statuses`` returned.

    Returns:
        Exactly four :class:`~appdb.daemon_status.DaemonStatus` objects, one
        per known daemon.
    """
    by_name = {row.name: row for row in rows}
    resolved: list[DaemonStatus] = []
    for name in KNOWN_DAEMONS:
        present = by_name.get(name)
        if present is not None:
            resolved.append(present)
        else:
            resolved.append(
                DaemonStatus(
                    name=name,
                    state="stopped",
                    detail="no heartbeat recorded",
                    processed_count=0,
                    last_heartbeat=_NEVER,
                )
            )
    return resolved


def overall_health(statuses: list[DaemonStatus]) -> OverallHealth:
    """Roll the per-daemon states into the dashboard's overall verdict.

    - ``ok`` — every daemon is ``running`` or ``idle``.
    - ``down`` — every daemon is ``stopped``.
    - ``degraded`` — anything in between (at least one stopped, not all).

    Args:
        statuses: The resolved per-daemon statuses (all four daemons).

    Returns:
        The overall-health verdict.
    """
    stopped = sum(1 for s in statuses if s.state == "stopped")
    if stopped == 0:
        return "ok"
    if stopped == len(statuses):
        return "down"
    return "degraded"
