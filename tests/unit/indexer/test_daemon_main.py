"""Tests for indexer.daemon.main() and the _interruptible_wait helper.

Behavioural promises tested:

- A contended flock causes main() to exit non-zero; a successful lock
  acquisition lets main() proceed.
- _interruptible_wait returns False on shutdown or after the full duration,
  and returns True (deleting the sentinel) when a manual-trigger sentinel is
  present.
- _interruptible_wait calls beat_idle on the cycle_recorder at _IDLE_BEAT_INTERVAL
  intervals so the daemon heartbeat stays fresh during a 300 s reconcile wait.

The _run_loop behaviours live in test_daemon.py — the daemon's tests are split
across two files for the 500-line ceiling (CODE_GUIDELINES §3.1).  The
``_reset_shutdown`` autouse fixture comes from tests/unit/indexer/conftest.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import common.shutdown as shutdown_mod
from indexer.daemon import _IDLE_BEAT_INTERVAL, _WAKE_CHECK_INTERVAL, _interruptible_wait
from tests.helpers.factories import make_settings_obj


def _make_reconciler() -> MagicMock:
    """Return a mock Reconciler whose two operations report empty outcomes."""
    reconciler = MagicMock()
    reconciler.incremental_sync.return_value = MagicMock(
        indexed=0, metadata_only=0, skipped=0, failed=0, given_up=0
    )
    reconciler.deletion_sweep.return_value = MagicMock(
        pruned=0, aborted=False, candidates=0
    )
    return reconciler


# ---------------------------------------------------------------------------
# main() — flock acquisition decides whether the daemon starts
# ---------------------------------------------------------------------------


def test_main_exits_nonzero_when_lock_contended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main() calls sys.exit with a non-zero code when the flock is already held."""
    from indexer.lock import IndexerLockError

    # Patch acquire_writer_lock to simulate a contended lock.
    monkeypatch.setattr(
        "indexer.daemon.acquire_writer_lock",
        lambda path: (_ for _ in ()).throw(IndexerLockError("lock held")),
    )
    # daemon.main() now calls current_settings() (the hot-load accessor), so
    # the stand-in is patched directly on the daemon module — Wave 4 switched
    # the entry point off Settings.from_environment().
    settings = make_settings_obj(INDEX_DB_PATH=str(tmp_path / "index.db"))
    monkeypatch.setattr("indexer.daemon.current_settings", lambda *a, **kw: settings)
    monkeypatch.setattr("indexer.daemon.configure_logging", lambda s: None)
    monkeypatch.setattr("indexer.daemon.setup_libraries", lambda s: None)

    with pytest.raises(SystemExit) as exc_info:
        from indexer import daemon

        daemon.main()

    assert exc_info.value.code != 0


def test_main_proceeds_when_lock_acquired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main() does not exit non-zero when the flock is successfully acquired."""
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
            "indexer.daemon.current_settings", lambda *a, **kw: settings
        )
        monkeypatch.setattr("indexer.daemon.configure_logging", lambda s: None)
        monkeypatch.setattr("indexer.daemon.setup_libraries", lambda s: None)
        monkeypatch.setattr(
            "indexer.daemon.acquire_writer_lock", lambda path: lock_handle
        )
        monkeypatch.setattr("indexer.daemon.register_signal_handlers", lambda: None)
        # Preflight stubs.
        monkeypatch.setattr(
            "indexer.daemon.PaperlessClient",
            lambda s: MagicMock(ping=lambda: None),
        )
        embedding_client = MagicMock()
        embedding_client.embed.return_value = [[0.0]]
        monkeypatch.setattr(
            "indexer.daemon.EmbeddingClient", lambda s: embedding_client
        )
        store_writer = MagicMock()
        store_writer.check_embedding_model.return_value = False
        store_writer.checkpoint.return_value = None
        monkeypatch.setattr("indexer.daemon.StoreWriter", lambda s: store_writer)
        monkeypatch.setattr(
            "indexer.daemon.Reconciler", lambda **kwargs: _make_reconciler()
        )
        # Force the loop to exit immediately on entry.
        shutdown_mod.request_shutdown()

        from indexer import daemon

        # Should not raise SystemExit.
        daemon.main()
    finally:
        lock_handle.close()


# ---------------------------------------------------------------------------
# _interruptible_wait
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


def test_interruptible_wait_beats_idle_during_long_reconcile_interval(
    tmp_path: Path,
) -> None:
    """A 300 s reconcile interval must keep the indexer's heartbeat fresh.

    This is the BLOCKER 2 regression guard.  The default stale-after window is
    90 s; with RECONCILE_INTERVAL = 300 s the indexer's heartbeat would expire
    between cycles.  _interruptible_wait must call beat_idle on the recorder at
    least once per _IDLE_BEAT_INTERVAL seconds so the dashboard reads "idle"
    continuously rather than "stopped".

    The test advances a fake monotonic clock in slices of _IDLE_BEAT_INTERVAL
    and verifies that beat_idle is called at each interval boundary inside a
    300 s wait — without the 300 s actually elapsing.
    """
    sentinel_path = tmp_path / "reconcile.request"
    recorder = MagicMock()

    # We simulate 300 s worth of monotonic time via time.monotonic patches so
    # the test returns immediately.  Each call to time.monotonic() advances the
    # fake clock by _WAKE_CHECK_INTERVAL to drive the loop forward, while
    # time.sleep is a no-op.
    TOTAL_WAIT = 300.0
    start = 1000.0  # arbitrary epoch offset

    # Produce enough fake-clock readings for the loop plus a sentinel check.
    # The loop ticks in _WAKE_CHECK_INTERVAL increments; we need enough values
    # to simulate the full 300 s wait.  Add a few extras so the generator does
    # not run dry.
    ticks = int(TOTAL_WAIT / _WAKE_CHECK_INTERVAL) + 10
    # Two calls per iteration (once for the beat check, once for remaining calc)
    # plus the initial deadline call and a few guards.
    clock_readings = [start + i * _WAKE_CHECK_INTERVAL for i in range(ticks * 3 + 20)]
    clock_iter = iter(clock_readings)

    with patch("indexer.daemon.time.monotonic", side_effect=lambda: next(clock_iter)):
        with patch("indexer.daemon.time.sleep"):
            _interruptible_wait(
                seconds=TOTAL_WAIT,
                sentinel_path=sentinel_path,
                cycle_recorder=recorder,
            )

    # beat_idle must have been called roughly once per _IDLE_BEAT_INTERVAL.
    # The final slice may end at the deadline before the last beat fires, so
    # we allow one fewer call than the exact quotient.
    minimum_beats = int(TOTAL_WAIT / _IDLE_BEAT_INTERVAL) - 1
    assert recorder.beat_idle.call_count >= minimum_beats, (
        f"Expected at least {minimum_beats} beat_idle calls for a "
        f"{TOTAL_WAIT}s wait with _IDLE_BEAT_INTERVAL={_IDLE_BEAT_INTERVAL}s; "
        f"got {recorder.beat_idle.call_count}"
    )
    assert recorder.beat_idle.call_count > 0, "beat_idle was never called"
