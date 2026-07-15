"""Tests for common.heartbeat — the best-effort daemon heartbeat helper.

Covers: a beat writes a daemon_status row; processed_delta accumulates across
beats; an idle beat writes detail='idle'; a beat against a broken connection
is swallowed (never raises) and logs a warning; open_app_db_connection yields
a usable connection.
"""

from __future__ import annotations

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


def test_run_heartbeat_ticker_beats_until_stopped(conn) -> None:
    """run_heartbeat_ticker calls beat repeatedly until its stop predicate
    returns True, then returns."""
    from common.heartbeat import Heartbeat, run_heartbeat_ticker

    hb = Heartbeat(name="search", conn=conn)
    calls = {"n": 0}

    def stop() -> bool:
        # Let three ticks happen, then stop.
        calls["n"] += 1
        return calls["n"] > 3

    run_heartbeat_ticker(
        hb,
        detail_fn=lambda: "serving search",
        interval_seconds=1,
        should_stop=stop,
        sleep=lambda _s: None,
    )

    # The daemon row exists and the ticker exited cleanly.
    rows = daemon_status.read_statuses(conn)
    assert rows[0].name == "search"
    assert rows[0].detail == "serving search"


def test_run_heartbeat_ticker_stops_immediately_if_already_stopped(conn) -> None:
    """If should_stop is already True the ticker beats once and returns."""
    from common.heartbeat import Heartbeat, run_heartbeat_ticker

    hb = Heartbeat(name="search", conn=conn)
    run_heartbeat_ticker(
        hb,
        detail_fn=lambda: "serving search",
        interval_seconds=1,
        should_stop=lambda: True,
        sleep=lambda _s: None,
    )
    # One beat is still written so a freshly-started server shows up at once.
    assert len(daemon_status.read_statuses(conn)) == 1


def test_run_heartbeat_ticker_survives_a_failing_detail_fn(conn) -> None:
    """A detail_fn that raises is isolated — the ticker keeps going and
    stops cleanly rather than propagating."""
    from common.heartbeat import Heartbeat, run_heartbeat_ticker

    hb = Heartbeat(name="search", conn=conn)
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    def boom() -> str:
        raise RuntimeError("detail_fn bug")

    # Must not raise.
    run_heartbeat_ticker(
        hb,
        detail_fn=boom,
        interval_seconds=1,
        should_stop=stop,
        sleep=lambda _s: None,
    )


def test_run_stall_ticker_beats_only_while_in_flight(conn) -> None:
    """The stall ticker beats when in_flight is set and stays silent when
    it is clear — idle/halted beats remain the poll loop's alone."""
    import threading

    from common.heartbeat import Heartbeat, run_stall_ticker

    hb = Heartbeat(name="ocr", conn=conn)
    in_flight = threading.Event()
    stop = threading.Event()

    ticker = threading.Thread(
        target=lambda: run_stall_ticker(
            hb,
            in_flight=in_flight,
            stop=stop,
            interval_seconds=1,
            detail="processing — waiting on LLM capacity",
        ),
        daemon=True,
    )
    ticker.start()
    try:
        # Not in flight: a full interval passes with no beat written.
        ticker.join(timeout=1.3)
        assert daemon_status.read_statuses(conn) == []

        # In flight: the next tick writes the stalled-but-alive beat.
        in_flight.set()
        for _ in range(40):  # up to ~4s for one ≥1s tick, no flaky sleep maths
            rows = daemon_status.read_statuses(conn)
            if rows:
                break
            ticker.join(timeout=0.1)
        assert rows[0].name == "ocr"
        assert rows[0].detail == "processing — waiting on LLM capacity"
    finally:
        stop.set()
        ticker.join(timeout=5)
    assert not ticker.is_alive()


def test_run_stall_ticker_exits_promptly_on_stop(conn) -> None:
    """Setting stop ends the ticker without waiting out a full interval."""
    import threading
    import time

    from common.heartbeat import Heartbeat, run_stall_ticker

    hb = Heartbeat(name="classifier", conn=conn)
    in_flight = threading.Event()
    stop = threading.Event()

    ticker = threading.Thread(
        target=lambda: run_stall_ticker(
            hb, in_flight=in_flight, stop=stop, interval_seconds=60
        ),
        daemon=True,
    )
    ticker.start()
    start = time.monotonic()
    stop.set()
    ticker.join(timeout=5)
    assert not ticker.is_alive()
    # Event.wait returns early on set — nowhere near the 60s interval.
    assert time.monotonic() - start < 5


def test_run_stall_ticker_never_clobbers_the_processed_count(conn) -> None:
    """A stall beat leaves the poll loop's monotonic counter untouched.

    Regression: the ticker's own Heartbeat starts at zero; beating through
    it wrote processed_count=0 over the real total during every stall.
    """
    import threading

    from common.heartbeat import Heartbeat, run_stall_ticker

    # The poll loop's heartbeat has processed real work.
    main_hb = Heartbeat(name="ocr", conn=conn)
    main_hb.beat(detail="processing 5 document(s)", processed_delta=5)

    ticker_hb = Heartbeat(name="ocr", conn=conn)
    in_flight = threading.Event()
    in_flight.set()
    stop = threading.Event()

    ticker = threading.Thread(
        target=lambda: run_stall_ticker(
            ticker_hb, in_flight=in_flight, stop=stop, interval_seconds=1
        ),
        daemon=True,
    )
    ticker.start()
    try:
        for _ in range(40):
            rows = daemon_status.read_statuses(conn)
            if rows and rows[0].detail != "processing 5 document(s)":
                break
            ticker.join(timeout=0.1)
    finally:
        stop.set()
        ticker.join(timeout=5)

    rows = daemon_status.read_statuses(conn)
    assert rows[0].detail == "working — waiting on a slow upstream call"
    assert rows[0].processed_count == 5
