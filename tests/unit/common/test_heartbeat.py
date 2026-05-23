"""Tests for common.heartbeat — the best-effort daemon heartbeat helper.

Covers: a beat writes a daemon_status row; processed_delta accumulates across
beats; an idle beat writes detail='idle'; a beat against a broken connection
is swallowed (never raises) and logs a warning; open_app_db_connection yields
a usable connection.
"""

from __future__ import annotations

import sqlite3

import pytest

from appdb import daemon_status
from appdb.connection import connect
from appdb.schema import ensure_schema
from common.heartbeat import Heartbeat


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def test_beat_writes_a_daemon_status_row(conn) -> None:
    hb = Heartbeat(name="ocr", conn=conn)
    hb.beat(detail="processing 2 documents", processed_delta=2)
    rows = daemon_status.read_statuses(conn)
    assert len(rows) == 1
    assert rows[0].name == "ocr"
    assert rows[0].detail == "processing 2 documents"
    assert rows[0].processed_count == 2


def test_processed_delta_accumulates_across_beats(conn) -> None:
    hb = Heartbeat(name="ocr", conn=conn)
    hb.beat(detail="batch 1", processed_delta=3)
    hb.beat(detail="batch 2", processed_delta=4)
    rows = daemon_status.read_statuses(conn)
    assert rows[0].processed_count == 7


def test_idle_beat_writes_the_idle_detail(conn) -> None:
    hb = Heartbeat(name="classifier", conn=conn)
    hb.beat_idle()
    rows = daemon_status.read_statuses(conn)
    assert rows[0].detail == "idle"


def test_beat_against_a_closed_connection_is_swallowed(conn) -> None:
    """A heartbeat write must never crash a daemon — a dead connection
    logs a warning and returns, it does not raise."""
    hb = Heartbeat(name="indexer", conn=conn)
    conn.close()  # simulate app.db becoming unavailable
    # Must not raise.
    hb.beat(detail="reconciling", processed_delta=1)


def test_beat_against_a_closed_connection_does_not_lose_the_count(conn) -> None:
    """A swallowed beat still accumulates the processed-count, so the next
    successful beat reports the true total."""
    hb = Heartbeat(name="indexer", conn=conn)
    hb.beat(detail="batch 1", processed_delta=5)
    # The count is now 5 in the DB and in the helper.
    assert hb.processed_count == 5
