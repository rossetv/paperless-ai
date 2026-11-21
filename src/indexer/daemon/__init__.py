"""Indexer reconciliation daemon entry point.

Boot order::

    1. Settings + logging + libraries
    2. Acquire OS flock on ``<INDEX_DB_PATH>.lock`` — another indexer aborts.
    3. Register SIGTERM / SIGINT shutdown handlers.
    4. Preflight: Paperless reachable, store writable, embedding model responds,
       check_embedding_model() (may trigger a rebuild).
    5. Construct Reconciler and StoreWriter.
    6. Enter the reconciliation loop.

Settings are re-read at the top of every cycle, so a config change in app.db
hot-loads.
"""

from __future__ import annotations

from indexer.daemon._boot import main
from indexer.daemon._loop import (
    _LoopState,
    _rebuild_reconciler,
    _run_loop,
    _run_one_cycle,
)
from indexer.daemon._wait import (
    _IDLE_BEAT_INTERVAL,
    _WAKE_CHECK_INTERVAL,
    _interruptible_wait,
)

__all__ = [
    "_IDLE_BEAT_INTERVAL",
    "_LoopState",
    "_WAKE_CHECK_INTERVAL",
    "_interruptible_wait",
    "_rebuild_reconciler",
    "_run_loop",
    "_run_one_cycle",
    "main",
]


if __name__ == "__main__":
    main()
