"""Request an index rebuild by dropping the indexer's sentinel files.

The search server never writes ``index.db``: the indexer holds the exclusive
writer flock and is its sole mutator, so the server asks for a rebuild through
sentinel files the indexer consumes on its next cycle.
"""

from __future__ import annotations

from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# Cross-process contract: indexer.daemon._loop keeps its own copy of these names.
REBUILD_SENTINEL_NAME = "rebuild.request"
RECONCILE_SENTINEL_NAME = "reconcile.request"


def request_index_rebuild(index_db_path: str) -> None:
    """Touch the rebuild + reconcile sentinels beside *index_db_path*.

    ``rebuild.request`` schedules the indexer's destructive wipe-and-re-index;
    ``reconcile.request`` wakes its interruptible wait so the rebuild is acted
    on within the wake-check interval, not a full ``RECONCILE_INTERVAL``.

    Raises:
        OSError: The index data directory is missing or not writable.
    """
    db_dir = Path(index_db_path).parent
    (db_dir / REBUILD_SENTINEL_NAME).touch()
    (db_dir / RECONCILE_SENTINEL_NAME).touch()
    log.warning("search.index_rebuild_requested", index_db_path=index_db_path)
