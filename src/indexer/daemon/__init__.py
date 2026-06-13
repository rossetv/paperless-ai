"""Indexer reconciliation daemon — package entry point.

Runs the semantic-search indexer: acquires the exclusive writer flock, performs
preflight checks, constructs the Reconciler, and enters the reconciliation loop.

Boot order::

    1. Settings + logging + libraries
    2. Acquire OS flock on ``<INDEX_DB_PATH>.lock`` — another indexer aborts.
    3. Register SIGTERM / SIGINT shutdown handlers.
    4. Preflight: Paperless reachable, store writable, embedding model responds,
       check_embedding_model() (may trigger a rebuild).
    5. Construct Reconciler and StoreWriter.
    6. Enter the reconciliation loop.

Configuration is loaded from app.db (the config table) layered over the
environment via common.config.current_settings, and re-checked at the top of
every reconciliation cycle so a config change hot-loads (web-redesign §5).

This package was split from a single ``daemon.py`` once it crossed the 500-line
ceiling (CODE_GUIDELINES §3.1, §3.3): the boot sequence lives in :mod:`._boot`,
the run-loop and its per-cycle body in :mod:`._loop`, and the inter-cycle wait
and sentinel helpers in :mod:`._wait`.  This ``__init__`` is a thin re-export so
``from indexer.daemon import main`` and the other historical import paths keep
working.

Allowed deps: store/ (StoreWriter), indexer/ (lock, reconciler), common/.
Forbidden: imports from search/, sqlite3, httpx direct, bare openai calls.
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
