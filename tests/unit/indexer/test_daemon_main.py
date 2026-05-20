"""Tests for indexer.daemon.main() and the _interruptible_wait helper.

Behavioural promises tested:

- A contended flock causes main() to exit non-zero; a successful lock
  acquisition lets main() proceed.
- _interruptible_wait returns False on shutdown or after the full duration,
  and returns True (deleting the sentinel) when a manual-trigger sentinel is
  present.

The _run_loop behaviours live in test_daemon.py — the daemon's tests are split
across two files for the 500-line ceiling (CODE_GUIDELINES §3.1).  The
``_reset_shutdown`` autouse fixture comes from tests/unit/indexer/conftest.py.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import common.shutdown as shutdown_mod
from indexer.daemon import _WAKE_CHECK_INTERVAL, _interruptible_wait
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
    # daemon.main() calls Settings.from_environment(), so the stand-in must
    # expose that classmethod.
    settings = make_settings_obj(INDEX_DB_PATH=str(tmp_path / "index.db"))
    monkeypatch.setattr(
        "indexer.daemon.Settings",
        SimpleNamespace(from_environment=lambda: settings),
    )
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
            "indexer.daemon.Settings",
            SimpleNamespace(from_environment=lambda: settings),
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
