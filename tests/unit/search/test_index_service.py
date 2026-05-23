"""Tests for search.index_service — the pure Index-dashboard shaping logic.

Covers: resolve_daemon_statuses fills every missing daemon in as 'stopped'
and always returns the four known daemons; overall_health is 'ok' when all
daemons are live, 'degraded' when some are stopped, 'down' when all are.
"""

from __future__ import annotations

from appdb.daemon_status import DaemonStatus
from search.index_service import (
    KNOWN_DAEMONS,
    overall_health,
    resolve_daemon_statuses,
)


def _status(name: str, state: str) -> DaemonStatus:
    """A DaemonStatus with placeholder heartbeat/detail fields."""
    return DaemonStatus(
        name=name,
        state=state,  # type: ignore[arg-type]
        detail="idle" if state == "idle" else state,
        processed_count=0,
        last_heartbeat="2026-05-22T12:00:00+00:00",
    )


def test_known_daemons_is_the_four_processes() -> None:
    assert KNOWN_DAEMONS == ("classifier", "indexer", "ocr", "search")


def test_resolve_returns_all_four_daemons() -> None:
    """Even with no rows at all, four daemons come back."""
    resolved = resolve_daemon_statuses([])
    assert {s.name for s in resolved} == set(KNOWN_DAEMONS)


def test_a_missing_daemon_is_synthesised_as_stopped() -> None:
    """A daemon with no heartbeat row is reported 'stopped'."""
    rows = [_status("ocr", "running")]
    resolved = {s.name: s for s in resolve_daemon_statuses(rows)}
    assert resolved["ocr"].state == "running"
    assert resolved["classifier"].state == "stopped"
    assert resolved["indexer"].state == "stopped"
    assert resolved["search"].state == "stopped"


def test_resolve_preserves_a_present_row() -> None:
    """A present row's fields are carried through unchanged."""
    rows = [_status("indexer", "running")]
    resolved = {s.name: s for s in resolve_daemon_statuses(rows)}
    assert resolved["indexer"].detail == "running"


def test_overall_health_is_ok_when_all_live() -> None:
    statuses = [
        _status("ocr", "running"),
        _status("classifier", "idle"),
        _status("indexer", "running"),
        _status("search", "running"),
    ]
    assert overall_health(statuses) == "ok"


def test_overall_health_is_degraded_when_some_stopped() -> None:
    statuses = [
        _status("ocr", "running"),
        _status("classifier", "stopped"),
        _status("indexer", "running"),
        _status("search", "running"),
    ]
    assert overall_health(statuses) == "degraded"


def test_overall_health_is_down_when_all_stopped() -> None:
    statuses = [
        _status("ocr", "stopped"),
        _status("classifier", "stopped"),
        _status("indexer", "stopped"),
        _status("search", "stopped"),
    ]
    assert overall_health(statuses) == "down"
