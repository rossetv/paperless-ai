"""Pure shaping logic for the Index operations dashboard (daemon tiles, health)."""

from __future__ import annotations

from typing import Literal

from appdb.daemon_status import DaemonStatus

# Sorted so the dashboard's tile order is stable.
KNOWN_DAEMONS: tuple[str, ...] = ("classifier", "indexer", "ocr", "search")

# A heartbeat timestamp for a daemon that has never written one. It is in the
# distant past so any downstream staleness check also treats it as stale.
_NEVER = "1970-01-01T00:00:00+00:00"

#: The overall-health verdict the dashboard hero renders.
OverallHealth = Literal["ok", "degraded", "down"]


def resolve_daemon_statuses(
    rows: list[DaemonStatus],
) -> list[DaemonStatus]:
    """Return one status per :data:`KNOWN_DAEMONS` entry, in that order.

    A daemon missing from *rows* has never written a heartbeat (e.g. a fresh
    install), so it is filled in as ``stopped``.
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
    """
    stopped = sum(1 for s in statuses if s.state == "stopped")
    if stopped == 0:
        return "ok"
    if stopped == len(statuses):
        return "down"
    return "degraded"
