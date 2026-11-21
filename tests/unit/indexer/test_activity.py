"""Tests for indexer.activity, the reconcile-activity and heartbeat recorder."""

from __future__ import annotations

import pytest

from appdb import daemon_status, reconcile_activity
from appdb.connection import connect
from appdb.schema import ensure_schema
from indexer.activity import IndexerActivityRecorder
from indexer.reconciler import SyncReport
from indexer.reconciler._sweep import SweepReport


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def test_record_sync_writes_a_sync_row(conn) -> None:
    recorder = IndexerActivityRecorder(conn)
    report = SyncReport(indexed=4, metadata_only=1, skipped=0, failed=0, given_up=0)
    recorder.record_sync(
        report,
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:08+00:00",
    )
    rows = reconcile_activity.read_recent(conn, limit=10)
    assert len(rows) == 1
    assert rows[0].kind == "sync"
    assert rows[0].ok is True
    assert rows[0].summary == {
        "indexed": 4,
        "metadata_only": 1,
        "skipped": 0,
        "failed": 0,
        "given_up": 0,
    }


def test_record_sync_beats_the_heartbeat(conn) -> None:
    recorder = IndexerActivityRecorder(conn)
    recorder.record_sync(
        SyncReport(indexed=2, metadata_only=0, skipped=0, failed=0, given_up=0),
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:05+00:00",
    )
    rows = daemon_status.read_statuses(conn)
    assert len(rows) == 1
    assert rows[0].name == "indexer"


def test_record_sync_with_failures_is_still_ok_at_the_row_level(conn) -> None:
    """``ok`` means the cycle completed; failure counts live in the summary."""
    recorder = IndexerActivityRecorder(conn)
    recorder.record_sync(
        SyncReport(indexed=1, metadata_only=0, skipped=0, failed=3, given_up=1),
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:05+00:00",
    )
    row = reconcile_activity.read_recent(conn, limit=10)[0]
    assert row.ok is True
    assert row.summary["failed"] == 3


def test_record_sweep_writes_a_sweep_row(conn) -> None:
    recorder = IndexerActivityRecorder(conn)
    recorder.record_sweep(
        SweepReport(pruned=2, aborted=False, candidates=2),
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:03+00:00",
    )
    row = reconcile_activity.read_recent(conn, limit=10)[0]
    assert row.kind == "sweep"
    assert row.ok is True
    assert row.summary == {"pruned": 2, "aborted": 0, "candidates": 2}


def test_record_sweep_marks_an_aborted_sweep_not_ok(conn) -> None:
    recorder = IndexerActivityRecorder(conn)
    recorder.record_sweep(
        SweepReport(pruned=0, aborted=True, candidates=0),
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:01+00:00",
    )
    assert reconcile_activity.read_recent(conn, limit=10)[0].ok is False


def test_record_against_a_closed_connection_is_swallowed(conn) -> None:
    """An activity-recording failure must never crash the indexer."""
    recorder = IndexerActivityRecorder(conn)
    conn.close()
    recorder.record_sync(
        SyncReport(indexed=0, metadata_only=0, skipped=0, failed=0, given_up=0),
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:01+00:00",
    )
    recorder.beat_idle()


def test_beat_idle_writes_an_idle_indexer_heartbeat(conn) -> None:
    recorder = IndexerActivityRecorder(conn)
    recorder.beat_idle()
    rows = daemon_status.read_statuses(conn)
    assert rows[0].name == "indexer"
    assert rows[0].detail == "idle"


def test_record_rebuild_writes_a_sync_kind_row(conn) -> None:
    """A rebuild is followed by a full re-index, so it records as a 'sync' row."""
    recorder = IndexerActivityRecorder(conn)
    recorder.record_rebuild(
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:02+00:00",
    )
    rows = reconcile_activity.read_recent(conn, limit=10)
    assert len(rows) == 1
    assert rows[0].kind == "sync"
    assert rows[0].ok is True
    assert "rebuilt" in rows[0].detail.lower()


def test_record_rebuild_against_a_closed_connection_is_swallowed(conn) -> None:
    recorder = IndexerActivityRecorder(conn)
    conn.close()
    recorder.record_rebuild(
        started_at="2026-05-22T12:00:00+00:00",
        finished_at="2026-05-22T12:00:02+00:00",
    )
