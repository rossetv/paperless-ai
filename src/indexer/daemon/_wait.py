"""The inter-cycle wait and the manual-trigger sentinel — pure, self-contained.

The two helpers the reconciliation loop uses to sleep between cycles and to
consume the manual-trigger sentinel file.  They are pure over their arguments
(``seconds``, ``sentinel_path``, ``cycle_recorder``) with no coupling to the
store writer or settings, so they live in their own leaf module of the
``indexer.daemon`` package (CODE_GUIDELINES §3.3).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from common.shutdown import is_shutdown_requested

if TYPE_CHECKING:
    from pathlib import Path

    from indexer.activity import IndexerActivityRecorder

log = structlog.get_logger(__name__)

# Duration of each sleep slice in _interruptible_wait.  Short enough to react
# to shutdown and manual triggers promptly; long enough to avoid busy-looping.
_WAKE_CHECK_INTERVAL: float = 5.0

# How often to beat the idle heartbeat during the inter-cycle wait.  Must be
# well below the stale-after threshold (90 s by default) so the dashboard
# never reads the indexer as "stopped" while it is simply waiting.
_IDLE_BEAT_INTERVAL: float = 30.0


def _interruptible_wait(
    seconds: float,
    sentinel_path: Path,
    cycle_recorder: IndexerActivityRecorder | None = None,
) -> bool:
    """Sleep for *seconds*, waking early on shutdown or a sentinel file.

    Sleeps in slices of ``_WAKE_CHECK_INTERVAL`` seconds.  On each slice:

    - If ``is_shutdown_requested()`` → return ``False`` (no manual trigger).
    - If *sentinel_path* exists → delete it and return ``True`` (manual trigger
      detected; the next cycle should include a deletion sweep).

    When *cycle_recorder* is provided the function beats an idle heartbeat
    every ``_IDLE_BEAT_INTERVAL`` seconds so the Index dashboard does not
    report the indexer as ``stopped`` during long inter-cycle waits.  The
    default reconcile interval (300 s) exceeds the stale-after threshold (90 s)
    by more than three times, so without this beat the dashboard routinely
    shows the indexer as stopped while it is healthy.

    Args:
        seconds: How long to wait in total.
        sentinel_path: Path to the manual-trigger sentinel file.
        cycle_recorder: Optional activity recorder — ``beat_idle`` is called
            periodically when provided.  ``None`` in tests that do not need
            heartbeat coverage.

    Returns:
        ``True`` if a manual-trigger sentinel was detected and consumed;
        ``False`` if the full duration elapsed or shutdown was requested.
    """
    deadline = time.monotonic() + seconds
    last_beat_at = time.monotonic()

    # Check sentinel immediately at entry — a sentinel written just before the
    # wait begins is detected without sleeping first.
    if sentinel_path.exists():
        sentinel_path.unlink(missing_ok=True)
        log.debug("indexer.sentinel_consumed_at_wait_entry")
        return True

    while time.monotonic() < deadline:
        if is_shutdown_requested():
            return False

        # Beat idle if enough time has elapsed since the last beat.
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

        if sentinel_path.exists():
            sentinel_path.unlink(missing_ok=True)
            log.debug("indexer.sentinel_consumed_mid_wait")
            return True

    return False


def _consume_sentinel(sentinel_path: Path) -> bool:
    """Delete *sentinel_path* and return True if it exists; else False.

    Used at cycle entry to consume a manual-trigger sentinel that may have been
    written while the previous cycle was running (SPEC §5.8).

    Args:
        sentinel_path: The sentinel file path.

    Returns:
        True if the sentinel was present and deleted; False otherwise.
    """
    if sentinel_path.exists():
        sentinel_path.unlink(missing_ok=True)
        return True
    return False
