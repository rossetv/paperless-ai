"""Request an index rebuild by dropping the indexer's sentinel files.

The search server never writes ``index.db`` — the indexer holds the exclusive
writer flock and is the sole mutator. To request a destructive rebuild the
server drops two sentinel files beside ``index.db``, which the indexer consumes
at its next cycle: ``rebuild.request`` schedules the wipe-and-re-index, and
``reconcile.request`` wakes the indexer's interruptible wait so it acts within
the wake-check interval rather than after a full ``RECONCILE_INTERVAL``.

Shared by the explicit "Rebuild index" button (:mod:`search.index_routes`) and
by a Settings save that changes a :data:`common.config.REINDEX_KEYS` key
(:mod:`search.settings_routes`) — both must force the same rebuild, so the
sentinel I/O lives in one place rather than being copied into each route.

Allowed deps: pathlib, structlog. Forbidden: fastapi, sqlite3, store, indexer.
"""

from __future__ import annotations

from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# The sentinel file names, written beside index.db and consumed by the indexer
# (whose own copy of these names is the other half of this cross-process
# contract — see indexer.daemon._loop).
REBUILD_SENTINEL_NAME = "rebuild.request"
RECONCILE_SENTINEL_NAME = "reconcile.request"


def request_index_rebuild(index_db_path: str) -> None:
    """Touch the rebuild + reconcile sentinels beside *index_db_path*.

    ``rebuild.request`` schedules the indexer's destructive wipe-and-re-index;
    ``reconcile.request`` wakes its interruptible wait so the rebuild is acted
    on within the wake-check interval, not a full ``RECONCILE_INTERVAL``.

    Writes ONLY the two sentinel files — never ``index.db`` itself.

    Args:
        index_db_path: Path to ``index.db``; the sentinels are written into its
            parent directory.

    Raises:
        OSError: The index data directory is missing or not writable. Callers
            translate this into their own error shape (a 503 for the explicit
            button, a logged best-effort failure for a settings save).
    """
    db_dir = Path(index_db_path).parent
    (db_dir / REBUILD_SENTINEL_NAME).touch()
    (db_dir / RECONCILE_SENTINEL_NAME).touch()
    log.warning("search.index_rebuild_requested", index_db_path=index_db_path)
