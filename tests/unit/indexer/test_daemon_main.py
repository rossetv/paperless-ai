"""Tests for indexer.daemon.main() and the _interruptible_wait helper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import common.shutdown as shutdown_mod
from indexer.daemon import (
    _IDLE_BEAT_INTERVAL,
    _WAKE_CHECK_INTERVAL,
    _interruptible_wait,
    _run_loop,
)
from tests.helpers.factories import make_settings_obj
from tests.unit.indexer.conftest import make_daemon_reconciler


def test_main_exits_nonzero_when_lock_contended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from indexer.lock import IndexerLockError

    monkeypatch.setattr(
        "indexer.daemon._boot.acquire_writer_lock",
        lambda path: (_ for _ in ()).throw(IndexerLockError("lock held")),
    )
    settings = make_settings_obj(INDEX_DB_PATH=str(tmp_path / "index.db"))
    monkeypatch.setattr(
        "indexer.daemon._boot.current_settings", lambda *a, **kw: settings
    )
    monkeypatch.setattr("indexer.daemon._boot.configure_logging", lambda s: None)
    monkeypatch.setattr("indexer.daemon._boot.setup_libraries", lambda s: None)

    with pytest.raises(SystemExit) as exc_info:
        from indexer import daemon

        daemon.main()

    assert exc_info.value.code != 0


def test_main_proceeds_when_lock_acquired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_file = tmp_path / "index.db.lock"
    lock_handle = open(str(lock_file), "wb")

    try:
        settings = make_settings_obj(
            INDEX_DB_PATH=str(tmp_path / "index.db"),
            RECONCILE_INTERVAL=1,
            DELETION_SWEEP_INTERVAL=3600,
            DOCUMENT_WORKERS=1,
        )
        monkeypatch.setattr(
            "indexer.daemon._boot.current_settings", lambda *a, **kw: settings
        )
        monkeypatch.setattr("indexer.daemon._boot.configure_logging", lambda s: None)
        monkeypatch.setattr("indexer.daemon._boot.setup_libraries", lambda s: None)
        monkeypatch.setattr(
            "indexer.daemon._boot.acquire_writer_lock", lambda path: lock_handle
        )
        monkeypatch.setattr(
            "indexer.daemon._boot.register_signal_handlers", lambda: None
        )
        # Preflight stubs.
        monkeypatch.setattr(
            "indexer.daemon._boot.PaperlessClient",
            lambda s: MagicMock(ping=lambda: None),
        )
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.0]]
        monkeypatch.setattr(
            "indexer.daemon._boot.EmbeddingClient", lambda s: embedding_client
        )
        store_writer = MagicMock()
        store_writer.check_embedding_model.return_value = False
        store_writer.checkpoint.return_value = None
        monkeypatch.setattr("indexer.daemon._boot.StoreWriter", lambda s: store_writer)
        monkeypatch.setattr(
            "indexer.daemon._boot.Reconciler", lambda **kwargs: make_daemon_reconciler()
        )
        # The loop exits on entry.
        shutdown_mod.request_shutdown()

        from indexer import daemon

        daemon.main()
    finally:
        lock_handle.close()


def test_main_opens_the_default_app_db_when_the_env_path_is_blank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_handle = open(str(tmp_path / "index.db.lock"), "wb")
    opened: list[str] = []
    try:
        settings = make_settings_obj(INDEX_DB_PATH=str(tmp_path / "index.db"))
        monkeypatch.setenv("APP_DB_PATH", "  ")
        monkeypatch.setattr(
            "indexer.daemon._boot.current_settings", lambda *a, **kw: settings
        )
        monkeypatch.setattr("indexer.daemon._boot.configure_logging", lambda s: None)
        monkeypatch.setattr("indexer.daemon._boot.setup_libraries", lambda s: None)
        monkeypatch.setattr(
            "indexer.daemon._boot.acquire_writer_lock", lambda path: lock_handle
        )
        monkeypatch.setattr(
            "indexer.daemon._boot.register_signal_handlers", lambda: None
        )
        monkeypatch.setattr(
            "indexer.daemon._boot._open_app_db", lambda path: opened.append(path)
        )
        # Preflight fails right after the app.db path is resolved.
        monkeypatch.setattr(
            "indexer.daemon._boot.PaperlessClient",
            lambda s: MagicMock(ping=MagicMock(side_effect=SystemExit(1))),
        )
        monkeypatch.setattr("indexer.daemon._boot.EmbeddingClient", MagicMock())
        monkeypatch.setattr("indexer.daemon._boot.StoreWriter", MagicMock())

        from indexer import daemon

        with pytest.raises(SystemExit):
            daemon.main()
    finally:
        lock_handle.close()

    assert opened == ["/data/app.db"]


def test_interruptible_wait_returns_false_on_shutdown(tmp_path: Path) -> None:
    sentinel_path = tmp_path / "reconcile.request"

    shutdown_mod.request_shutdown()
    triggered = _interruptible_wait(seconds=60.0, sentinel_path=sentinel_path)

    assert triggered is False


def test_interruptible_wait_returns_false_when_full_duration_elapses(
    tmp_path: Path,
) -> None:
    sentinel_path = tmp_path / "reconcile.request"

    triggered = _interruptible_wait(
        seconds=_WAKE_CHECK_INTERVAL * 0.5, sentinel_path=sentinel_path
    )

    assert triggered is False


def test_interruptible_wait_deletes_sentinel_and_returns_true(
    tmp_path: Path,
) -> None:
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()

    triggered = _interruptible_wait(seconds=60.0, sentinel_path=sentinel_path)

    assert triggered is True
    assert not sentinel_path.exists()


def test_interruptible_wait_beats_idle_during_long_reconcile_interval(
    tmp_path: Path,
) -> None:
    """The stale-after window is 90 s, so a 300 s wait must beat idle at least
    once per _IDLE_BEAT_INTERVAL or the dashboard would read "stopped".
    """
    sentinel_path = tmp_path / "reconcile.request"
    recorder = MagicMock()

    # Each time.monotonic() call advances a fake clock by _WAKE_CHECK_INTERVAL
    # and time.sleep is a no-op, so the 300 s wait returns immediately.
    TOTAL_WAIT = 300.0
    start = 1000.0  # arbitrary epoch offset

    # Extra readings so the iterator never runs dry: the loop reads the clock
    # more than once per iteration.
    ticks = int(TOTAL_WAIT / _WAKE_CHECK_INTERVAL) + 10
    clock_readings = [start + i * _WAKE_CHECK_INTERVAL for i in range(ticks * 3 + 20)]
    clock_iter = iter(clock_readings)

    with patch(
        "indexer.daemon._wait.time.monotonic", side_effect=lambda: next(clock_iter)
    ):
        with patch("indexer.daemon._wait.time.sleep"):
            _interruptible_wait(
                seconds=TOTAL_WAIT,
                sentinel_path=sentinel_path,
                cycle_recorder=recorder,
            )

    # The final slice may end at the deadline before the last beat fires.
    minimum_beats = int(TOTAL_WAIT / _IDLE_BEAT_INTERVAL) - 1
    assert recorder.beat_idle.call_count >= minimum_beats, (
        f"Expected at least {minimum_beats} beat_idle calls for a "
        f"{TOTAL_WAIT}s wait with _IDLE_BEAT_INTERVAL={_IDLE_BEAT_INTERVAL}s; "
        f"got {recorder.beat_idle.call_count}"
    )
    assert recorder.beat_idle.call_count > 0, "beat_idle was never called"


def test_manual_trigger_consumed_by_the_wait_forces_the_next_cycle_sweep(
    tmp_path: Path,
) -> None:
    """A reconcile.request landing mid-cycle forces a sweep on the next cycle.

    The real (unpatched) wait consumes the sentinel, so the loop must carry the
    wait's True result into the next cycle.  The clock stays at 1.0, so only the
    manual trigger can cause a sweep.
    """
    sentinel_path = tmp_path / "reconcile.request"
    reconciler = make_daemon_reconciler()
    sync_report = reconciler.incremental_sync.return_value
    syncs = 0

    def sync() -> MagicMock:
        nonlocal syncs
        syncs += 1
        if syncs == 1:
            sentinel_path.touch()  # POST /api/reconcile lands mid-cycle
        else:
            shutdown_mod.request_shutdown()
        return sync_report

    reconciler.incremental_sync.side_effect = sync
    settings = MagicMock(RECONCILE_INTERVAL=60, DELETION_SWEEP_INTERVAL=3600)

    with patch("indexer.daemon._loop.current_settings", return_value=settings):
        _run_loop(
            reconciler=reconciler,
            store_writer=MagicMock(),
            settings=settings,
            app_db_path=str(tmp_path / "app.db"),
            sentinel_path=sentinel_path,
            clock=lambda: 1.0,
        )

    assert syncs == 2
    reconciler.deletion_sweep.assert_called_once()
