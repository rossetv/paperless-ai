"""Reconciliation engine for the semantic-search indexer.

The reconciler is the indexer's correctness-critical core.  It drives the two
operations the daemon loop (SPEC §5.1) calls in turn — ``incremental_sync`` and
``deletion_sweep`` — via the :class:`Reconciler` facade.

The package is split by concept (CODE_GUIDELINES §3.2, §3.3):

- :mod:`indexer.reconciler._incremental` — the watermark-driven incremental
  sync, the taxonomy refresh, and the worker-pool fan-out (SPEC §5.2, §5.5).
- :mod:`indexer.reconciler._failed_documents` — the bounded failed-document
  retry and dead-lettering machinery (SPEC §5.7).
- :mod:`indexer.reconciler._sweep` — the deletion sweep with its absolute
  "a partial enumeration prunes nothing" safety rule (SPEC §5.4).
- :mod:`indexer.reconciler._reconciler` — the :class:`Reconciler` facade that
  owns the long-lived clients and the per-document worker and delegates to the
  three concept-modules.

Allowed deps: store/ (the StoreWriter), indexer.worker, common/.
Forbidden: sqlite3, httpx, openai direct calls, imports from search/.
"""

from __future__ import annotations

from indexer.reconciler._failed_documents import (
    MAX_CONSECUTIVE_DOCUMENT_FAILURES,
)
from indexer.reconciler._incremental import OVERLAP_MARGIN, SyncReport
from indexer.reconciler._reconciler import Reconciler
from indexer.reconciler._sweep import SweepReport

__all__ = [
    "MAX_CONSECUTIVE_DOCUMENT_FAILURES",
    "OVERLAP_MARGIN",
    "Reconciler",
    "SweepReport",
    "SyncReport",
]
