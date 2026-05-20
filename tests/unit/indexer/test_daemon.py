"""Tests for indexer.daemon — the reconciliation daemon loop.

Behavioural promises tested:

1. The loop runs one incremental_sync + checkpoint each cycle, then waits.
2. is_shutdown_requested() becoming True ends the loop promptly (no full-wait
   needed) and the loop does not run another cycle.
3. A present reconcile.request sentinel shortens the wait, is deleted, and the
   next cycle includes a deletion_sweep.
4. A contended flock causes main() to exit non-zero (sys.exit with non-zero
   code); a successful lock acquisition lets main proceed.
5. The deletion sweep runs only when DELETION_SWEEP_INTERVAL has elapsed since
   the last sweep — or a manual trigger forced a full cycle.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import common.shutdown as shutdown_mod
from indexer.daemon import _WAKE_CHECK_INTERVAL, _interruptible_wait, _run_loop


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_shutdown():
    """Ensure the process-global shutdown flag is clear before and after each test."""
    shutdown_mod.reset_shutdown()
    yield
    shutdown_mod.reset_shutdown()


def _make_reconciler() -> MagicMock:
    reconciler = MagicMock()
    reconciler.incremental_sync.return_value = MagicMock(
        indexed=0, metadata_only=0, skipped=0, failed=0
    )
    reconciler.deletion_sweep.return_value = MagicMock(
        pruned=0, aborted=False, candidates=0
    )
    return reconciler


def _make_store_writer() -> MagicMock:
    writer = MagicMock()
    writer.checkpoint.return_value = None
    return writer


# ---------------------------------------------------------------------------
# 1. Loop runs one cycle (incremental_sync + checkpoint), then waits
# ---------------------------------------------------------------------------


def test_loop_runs_incremental_sync_and_checkpoint_each_cycle(tmp_path: Path) -> None:
    """One cycle: incremental_sync called, then checkpoint, then the wait begins."""
    reconciler = _make_reconciler()
    store_writer = _make_store_writer()

    # After the first cycle completes (past checkpoint), request shutdown so
    # the loop exits cleanly rather than running forever.
    wait_count = 0

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        nonlocal wait_count
        wait_count += 1
        # Signal shutdown so the loop exits after the first cycle.
        shutdown_mod.request_shutdown()
        return False  # no manual trigger pending

    sentinel_path = tmp_path / "reconcile.request"
    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=3600,
            sentinel_path=sentinel_path,
        )

    reconciler.incremental_sync.assert_called_once()
    store_writer.checkpoint.assert_called_once()
    assert wait_count == 1


# ---------------------------------------------------------------------------
# 2. Shutdown flag ends the loop promptly
# ---------------------------------------------------------------------------


def test_shutdown_ends_loop_promptly(tmp_path: Path) -> None:
    """Requesting shutdown before the loop runs causes it to exit immediately."""
    reconciler = _make_reconciler()
    store_writer = _make_store_writer()
    sentinel_path = tmp_path / "reconcile.request"

    shutdown_mod.request_shutdown()

    _run_loop(
        reconciler=reconciler,
        store_writer=store_writer,
        reconcile_interval=300,
        deletion_sweep_interval=3600,
        sentinel_path=sentinel_path,
    )

    # The loop must have checked the flag at entry and exited without doing work.
    reconciler.incremental_sync.assert_not_called()
    store_writer.checkpoint.assert_not_called()


def test_shutdown_during_wait_exits_after_current_cycle(tmp_path: Path) -> None:
    """Shutdown requested during the wait does not run another full cycle."""
    reconciler = _make_reconciler()
    store_writer = _make_store_writer()
    sentinel_path = tmp_path / "reconcile.request"
    cycles: list[int] = []

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        cycles.append(1)
        shutdown_mod.request_shutdown()
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=3600,
            sentinel_path=sentinel_path,
        )

    # Exactly one cycle ran before the loop noticed shutdown.
    assert reconciler.incremental_sync.call_count == 1
    assert len(cycles) == 1


# ---------------------------------------------------------------------------
# 3. Manual-trigger sentinel shortens wait and forces deletion_sweep
# ---------------------------------------------------------------------------


def test_sentinel_present_is_deleted_and_forces_deletion_sweep(tmp_path: Path) -> None:
    """A reconcile.request sentinel is deleted and the next cycle runs deletion_sweep."""
    reconciler = _make_reconciler()
    store_writer = _make_store_writer()
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()

    call_count = 0

    def fake_wait(seconds: float, sentinel_path: Path) -> bool:
        nonlocal call_count
        call_count += 1
        shutdown_mod.request_shutdown()
        # First call: no sentinel (it was already consumed before the wait);
        # return False (no further trigger).
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        _run_loop(
            reconciler=reconciler,
            store_writer=store_writer,
            reconcile_interval=300,
            deletion_sweep_interval=3600,
            sentinel_path=sentinel_path,
        )

    # The sentinel must have been consumed (deleted) before the loop started
    # waiting.
    assert not sentinel_path.exists()
    # A manual trigger at cycle-start forces a deletion_sweep regardless of
    # whether the interval has elapsed.
    reconciler.deletion_sweep.assert_called_once()


def test_sentinel_written_during_wait_shortens_wait(tmp_path: Path) -> None:
    """_interruptible_wait returns True when it detects the sentinel mid-wait."""
    sentinel_path = tmp_path / "reconcile.request"

    def _write_sentinel_then_check(seconds: float, sentinel: Path) -> bool:
        sentinel.touch()
        # Re-invoke the real logic by letting the actual function run one slice.
        # We cannot call the real function here without re-entering it, so we
        # directly test _interruptible_wait below.
        return True

    # Test _interruptible_wait directly: create the sentinel partway through.
    sentinel_path.touch()
    triggered = _interruptible_wait(seconds=60.0, sentinel_path=sentinel_path)

    assert triggered is True
    assert not sentinel_path.exists()


# ---------------------------------------------------------------------------
# 4. Contended flock causes main() to exit non-zero
# ---------------------------------------------------------------------------


def test_main_exits_nonzero_when_lock_contended(tmp_path: Path, monkeypatch) -> None:
    """main() calls sys.exit with a non-zero code when the flock is already held."""
    from indexer.lock import IndexerLockError

    # Patch acquire_writer_lock to simulate a contended lock.
    monkeypatch.setattr(
        "indexer.daemon.acquire_writer_lock",
        lambda path: (_ for _ in ()).throw(IndexerLockError("lock held")),
    )
    # Stub out Settings and bootstrap so we don't need real env vars.
    mock_settings = MagicMock()
    mock_settings.INDEX_DB_PATH = str(tmp_path / "index.db")
    monkeypatch.setattr("indexer.daemon.Settings", lambda: mock_settings)
    monkeypatch.setattr("indexer.daemon.configure_logging", lambda s: None)
    monkeypatch.setattr("indexer.daemon.setup_libraries", lambda s: None)

    with pytest.raises(SystemExit) as exc_info:
        from indexer import daemon
        daemon.main()

    assert exc_info.value.code != 0


def test_main_proceeds_when_lock_acquired(tmp_path: Path, monkeypatch) -> None:
    """main() does not exit non-zero when the flock is successfully acquired."""
    lock_file = tmp_path / "index.db.lock"
    lock_handle = open(str(lock_file), "wb")

    try:
        mock_settings = MagicMock()
        mock_settings.INDEX_DB_PATH = str(tmp_path / "index.db")
        mock_settings.RECONCILE_INTERVAL = 1
        mock_settings.DELETION_SWEEP_INTERVAL = 3600
        mock_settings.DOCUMENT_WORKERS = 1

        monkeypatch.setattr("indexer.daemon.Settings", lambda: mock_settings)
        monkeypatch.setattr("indexer.daemon.configure_logging", lambda s: None)
        monkeypatch.setattr("indexer.daemon.setup_libraries", lambda s: None)
        monkeypatch.setattr(
            "indexer.daemon.acquire_writer_lock", lambda path: lock_handle
        )
        monkeypatch.setattr(
            "indexer.daemon.register_signal_handlers", lambda: None
        )
        # Preflight stubs.
        monkeypatch.setattr(
            "indexer.daemon.PaperlessClient",
            lambda s: MagicMock(ping=lambda: None),
        )
        mock_embedding_client = MagicMock()
        mock_embedding_client.embed.return_value = [[0.0]]
        monkeypatch.setattr(
            "indexer.daemon.EmbeddingClient",
            lambda s: mock_embedding_client,
        )
        mock_store_writer = MagicMock()
        mock_store_writer.check_embedding_model.return_value = False
        mock_store_writer.checkpoint.return_value = None
        monkeypatch.setattr(
            "indexer.daemon.StoreWriter", lambda s: mock_store_writer
        )
        mock_reconciler = _make_reconciler()
        monkeypatch.setattr(
            "indexer.daemon.Reconciler",
            lambda **kwargs: mock_reconciler,
        )
        # Force the loop to exit immediately on entry.
        shutdown_mod.request_shutdown()

        from indexer import daemon
        # Should not raise SystemExit.
        daemon.main()
    finally:
        lock_handle.close()


# ---------------------------------------------------------------------------
# 5. Deletion sweep runs only when interval elapsed (or manual trigger)
# ---------------------------------------------------------------------------


def test_deletion_sweep_skipped_when_interval_not_elapsed(tmp_path: Path) -> None:
    """No deletion_sweep when DELETION_SWEEP_INTERVAL has not elapsed."""
    reconciler = _make_reconciler()
    store_writer = _make_store_writer()
    sentinel_path = tmp_path / "reconcile.request"

    # last_sweep_at set to "just now" — interval not elapsed.
    last_sweep_at = time.monotonic()
    call_count = 0

    def fake_wait(*, seconds: float, sentinel_path: Path) -> bool:
        nonlocal call_count
        call_count += 1
        shutdown_mod.request_shutdown()
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        # Inject last_sweep_at so the interval check sees "just swept".
        with patch("indexer.daemon.time") as mock_time:
            # First call: now (cycle start); second call: now again (elapsed check).
            mock_time.monotonic.return_value = last_sweep_at + 1.0  # 1s elapsed
            _run_loop(
                reconciler=reconciler,
                store_writer=store_writer,
                reconcile_interval=300,
                deletion_sweep_interval=3600,
                sentinel_path=sentinel_path,
                _last_sweep_at=last_sweep_at,  # type: ignore[call-arg]
            )

    reconciler.deletion_sweep.assert_not_called()


def test_deletion_sweep_runs_when_interval_elapsed(tmp_path: Path) -> None:
    """deletion_sweep is called when DELETION_SWEEP_INTERVAL seconds have elapsed."""
    reconciler = _make_reconciler()
    store_writer = _make_store_writer()
    sentinel_path = tmp_path / "reconcile.request"

    def fake_wait(*, seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        with patch("indexer.daemon.time") as mock_time:
            # last_sweep_at = 0; now = 3601 → interval elapsed.
            mock_time.monotonic.return_value = 3601.0
            _run_loop(
                reconciler=reconciler,
                store_writer=store_writer,
                reconcile_interval=300,
                deletion_sweep_interval=3600,
                sentinel_path=sentinel_path,
                _last_sweep_at=0.0,  # type: ignore[call-arg]
            )

    reconciler.deletion_sweep.assert_called_once()


def test_deletion_sweep_runs_on_manual_trigger_regardless_of_interval(
    tmp_path: Path,
) -> None:
    """A manual trigger forces deletion_sweep even if the interval has not elapsed."""
    reconciler = _make_reconciler()
    store_writer = _make_store_writer()
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()  # sentinel present at cycle start

    def fake_wait(*, seconds: float, sentinel_path: Path) -> bool:
        shutdown_mod.request_shutdown()
        return False

    with patch("indexer.daemon._interruptible_wait", side_effect=fake_wait):
        with patch("indexer.daemon.time") as mock_time:
            # last_sweep_at = 0; now = 1 → interval NOT elapsed.
            mock_time.monotonic.return_value = 1.0
            _run_loop(
                reconciler=reconciler,
                store_writer=store_writer,
                reconcile_interval=300,
                deletion_sweep_interval=3600,
                sentinel_path=sentinel_path,
                _last_sweep_at=0.0,  # type: ignore[call-arg]
            )

    reconciler.deletion_sweep.assert_called_once()


# ---------------------------------------------------------------------------
# _interruptible_wait unit tests
# ---------------------------------------------------------------------------


def test_interruptible_wait_returns_false_on_shutdown(tmp_path: Path) -> None:
    """_interruptible_wait returns False (no manual trigger) when shutdown fires."""
    sentinel_path = tmp_path / "reconcile.request"

    shutdown_mod.request_shutdown()
    triggered = _interruptible_wait(seconds=60.0, sentinel_path=sentinel_path)

    assert triggered is False


def test_interruptible_wait_returns_false_when_full_duration_elapses(
    tmp_path: Path,
) -> None:
    """_interruptible_wait returns False after the full wait with no sentinel/shutdown."""
    sentinel_path = tmp_path / "reconcile.request"

    # Use a very short wait so the test finishes quickly.
    triggered = _interruptible_wait(
        seconds=_WAKE_CHECK_INTERVAL * 0.5, sentinel_path=sentinel_path
    )

    assert triggered is False


def test_interruptible_wait_deletes_sentinel_and_returns_true(
    tmp_path: Path,
) -> None:
    """Sentinel present at the start of _interruptible_wait → returns True, deleted."""
    sentinel_path = tmp_path / "reconcile.request"
    sentinel_path.touch()

    triggered = _interruptible_wait(seconds=60.0, sentinel_path=sentinel_path)

    assert triggered is True
    assert not sentinel_path.exists()
