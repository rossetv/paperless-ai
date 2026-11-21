"""Tests for appdb.daemon_status heartbeats and the derived daemon state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from appdb import daemon_status
from appdb.connection import connect
from appdb.schema import ensure_schema


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_read_statuses_is_empty_for_a_fresh_table(conn) -> None:
    assert daemon_status.read_statuses(conn) == []


def test_record_heartbeat_then_read_round_trips(conn) -> None:
    daemon_status.record_heartbeat(
        conn, name="ocr", detail="processing 3 documents", processed_count=12
    )
    rows = daemon_status.read_statuses(conn)
    assert len(rows) == 1
    assert rows[0].name == "ocr"
    assert rows[0].detail == "processing 3 documents"
    assert rows[0].processed_count == 12


def test_record_heartbeat_upserts_one_row(conn) -> None:
    daemon_status.record_heartbeat(conn, name="ocr", detail="idle", processed_count=0)
    daemon_status.record_heartbeat(conn, name="ocr", detail="busy", processed_count=5)
    rows = daemon_status.read_statuses(conn)
    assert len(rows) == 1
    assert rows[0].detail == "busy"
    assert rows[0].processed_count == 5
    count = conn.execute(
        "SELECT COUNT(*) FROM daemon_status WHERE name = 'ocr'"
    ).fetchone()[0]
    assert count == 1


def test_fresh_active_heartbeat_is_running(conn) -> None:
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    daemon_status.record_heartbeat(
        conn, name="ocr", detail="processing 2 documents", processed_count=2
    )
    rows = daemon_status.read_statuses(conn, now=now + timedelta(seconds=5))
    assert rows[0].state == "running"


def test_fresh_idle_heartbeat_is_idle(conn) -> None:
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    daemon_status.record_heartbeat(
        conn, name="classifier", detail="idle", processed_count=0
    )
    rows = daemon_status.read_statuses(conn, now=now + timedelta(seconds=5))
    assert rows[0].state == "idle"


def test_stale_heartbeat_is_stopped(conn) -> None:
    """Staleness wins over the detail: a stale 'reconciling' row is stopped."""
    stale = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    conn.execute(
        "INSERT INTO daemon_status "
        "(name, detail, processed_count, last_heartbeat, updated_at) "
        "VALUES ('indexer', 'reconciling', 9, ?, ?)",
        (_iso(stale), _iso(stale)),
    )
    conn.commit()
    # 'now' is well past the default staleness window.
    far_future = stale + timedelta(hours=1)
    rows = daemon_status.read_statuses(conn, now=far_future)
    assert rows[0].state == "stopped"


def test_read_statuses_returns_every_daemon(conn) -> None:
    for name in ("ocr", "classifier", "indexer", "search"):
        daemon_status.record_heartbeat(
            conn, name=name, detail="idle", processed_count=0
        )
    names = {row.name for row in daemon_status.read_statuses(conn)}
    assert names == {"ocr", "classifier", "indexer", "search"}


def test_custom_staleness_window_is_honoured(conn) -> None:
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    daemon_status.record_heartbeat(
        conn, name="search", detail="serving", processed_count=0
    )
    rows = daemon_status.read_statuses(
        conn,
        now=now + timedelta(minutes=30),
        stale_after_seconds=3600,
    )
    assert rows[0].state == "running"


def test_touch_heartbeat_preserves_the_processed_count(conn) -> None:
    """touch_heartbeat refreshes detail and freshness but never the counter.

    The stall ticker's secondary Heartbeat holds no running total, so a full
    record_heartbeat from it would reset the persisted count to zero.
    """
    daemon_status.record_heartbeat(
        conn, name="ocr", detail="processing 3 documents", processed_count=12
    )
    daemon_status.touch_heartbeat(
        conn, name="ocr", detail="working — waiting on a slow upstream call"
    )
    rows = daemon_status.read_statuses(conn)
    assert rows[0].processed_count == 12
    assert rows[0].detail == "working — waiting on a slow upstream call"


def test_touch_heartbeat_seeds_a_new_row_at_zero(conn) -> None:
    daemon_status.touch_heartbeat(conn, name="classifier", detail="working")
    rows = daemon_status.read_statuses(conn)
    assert rows[0].name == "classifier"
    assert rows[0].processed_count == 0
