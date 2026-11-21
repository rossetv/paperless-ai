"""The indexer's inter-cycle wait and manual-trigger sentinel helpers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from common.shutdown import is_shutdown_requested

if TYPE_CHECKING:
    from pathlib import Path

    from indexer.activity import IndexerActivityRecorder

log = structlog.get_logger(__name__)

# Sleep slice: short enough to react to shutdown and triggers promptly.
_WAKE_CHECK_INTERVAL: float = 5.0

# Must be well below the heartbeat stale-after threshold (90 s by default) so
# the dashboard never reads a waiting indexer as stopped.
_IDLE_BEAT_INTERVAL: float = 30.0


def _interruptible_wait(
    seconds: float,
    sentinel_path: Path,
    cycle_recorder: IndexerActivityRecorder | None = None,
) -> bool:
    """Sleep for *seconds*, waking early on shutdown or a sentinel file.

    Returns ``True`` if the sentinel was found and consumed, ``False`` if the
    wait elapsed or shutdown was requested. With a *cycle_recorder* it beats
    idle every ``_IDLE_BEAT_INTERVAL``: the default 300 s reconcile interval is
    far past the 90 s stale-after threshold.
    """
    deadline = time.monotonic() + seconds
    last_beat_at = time.monotonic()

    if _consume_sentinel(sentinel_path):
        log.debug("indexer.sentinel_consumed_at_wait_entry")
        return True

    while time.monotonic() < deadline:
        if is_shutdown_requested():
            return False

        if cycle_recorder is not None:
            now = time.monotonic()
            if now - last_beat_at >= _IDLE_BEAT_INTERVAL:
                cycle_recorder.beat_idle()
                last_beat_at = now

        remaining = deadline - time.monotonic()
        slice_duration = min(_WAKE_CHECK_INTERVAL, remaining)
        if slice_duration <= 0:
            break
        time.sleep(slice_duration)

        if _consume_sentinel(sentinel_path):
            log.debug("indexer.sentinel_consumed_mid_wait")
            return True

    return False


def _consume_sentinel(sentinel_path: Path) -> bool:
    """Delete *sentinel_path* and return True if it existed."""
    if sentinel_path.exists():
        sentinel_path.unlink(missing_ok=True)
        return True
    return False
