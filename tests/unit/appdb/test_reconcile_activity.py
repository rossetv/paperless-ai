"""Tests for appdb.reconcile_activity, the reconcile-cycle activity log."""

from __future__ import annotations

import pytest

from appdb import reconcile_activity
from appdb.connection import connect
from appdb.schema import ensure_schema


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def test_read_recent_is_empty_for_a_fresh_table(conn) -> None:
    assert reconcile_activity.read_recent(conn, limit=10) == []


def test_record_cycle_then_read_round_trips(conn) -> None:
    reconcile_activity.record_cycle(
        conn,
        kind="sync",
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:05+00:00",
        ok=True,
        summary={"indexed": 3, "failed": 0, "skipped": 1},
        detail="indexed 3 documents",
    )
    rows = reconcile_activity.read_recent(conn, limit=10)
    assert len(rows) == 1
    assert rows[0].kind == "sync"
    assert rows[0].ok is True
    assert rows[0].summary == {"indexed": 3, "failed": 0, "skipped": 1}
    assert rows[0].detail == "indexed 3 documents"


def test_record_cycle_keeps_the_log_bounded(conn) -> None:
    """The log never grows past _ACTIVITY_CAP rows.

    A long-lived indexer records a cycle every few minutes for months, so
    record_cycle trims as it appends.
    """
    total = reconcile_activity._ACTIVITY_CAP + 25
    for i in range(total):
        reconcile_activity.record_cycle(
            conn,
            kind="sync",
            started_at="2026-05-22T12:00:00+00:00",
            finished_at="2026-05-22T12:00:05+00:00",
            ok=True,
            summary={"indexed": i},
            detail=f"cycle {i}",
        )

    count = conn.execute("SELECT COUNT(*) FROM reconcile_activity").fetchone()[0]
    assert count == reconcile_activity._ACTIVITY_CAP
    newest = reconcile_activity.read_recent(conn, limit=1)[0]
    assert newest.detail == f"cycle {total - 1}"


def test_read_recent_returns_newest_first(conn) -> None:
    for n in range(3):
        reconcile_activity.record_cycle(
            conn,
            kind="sync",
            started_at=f"2026-05-22T12:0{n}:00+00:00",
            finished_at=f"2026-05-22T12:0{n}:05+00:00",
            ok=True,
            summary={"indexed": n},
            detail=f"cycle {n}",
        )
    rows = reconcile_activity.read_recent(conn, limit=10)
    assert [row.detail for row in rows] == ["cycle 2", "cycle 1", "cycle 0"]


def test_read_recent_honours_the_limit(conn) -> None:
    for n in range(5):
        reconcile_activity.record_cycle(
            conn,
            kind="sweep",
            started_at=f"2026-05-22T12:0{n}:00+00:00",
            finished_at=f"2026-05-22T12:0{n}:05+00:00",
            ok=True,
            summary={"pruned": n},
            detail=f"sweep {n}",
        )
    rows = reconcile_activity.read_recent(conn, limit=2)
    assert len(rows) == 2
    assert [row.detail for row in rows] == ["sweep 4", "sweep 3"]


def test_record_cycle_stores_a_failed_cycle(conn) -> None:
    reconcile_activity.record_cycle(
        conn,
        kind="sweep",
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:01+00:00",
        ok=False,
        summary={"pruned": 0, "aborted": 1},
        detail="sweep aborted: enumeration failed",
    )
    rows = reconcile_activity.read_recent(conn, limit=10)
    assert rows[0].ok is False


def test_summary_round_trips_an_empty_dict(conn) -> None:
    reconcile_activity.record_cycle(
        conn,
        kind="sync",
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:01+00:00",
        ok=True,
        summary={},
        detail="no-op cycle",
    )
    assert reconcile_activity.read_recent(conn, limit=10)[0].summary == {}


def test_parse_summary_skips_non_int_values_without_raising(conn) -> None:
    """A malformed stored summary value is skipped; it must not 500 the dashboard."""
    conn.execute(
        "INSERT INTO reconcile_activity "
        "(kind, started_at, finished_at, ok, summary, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "sync",
            "2026-05-22T12:00:00+00:00",
            "2026-05-22T12:00:01+00:00",
            1,
            '{"indexed": [1, 2], "failed": 0}',  # "indexed" is a list, not int
            "malformed summary row",
        ),
    )
    conn.commit()

    rows = reconcile_activity.read_recent(conn, limit=10)
    assert len(rows) == 1
    assert rows[0].summary == {"failed": 0}
    assert "indexed" not in rows[0].summary
