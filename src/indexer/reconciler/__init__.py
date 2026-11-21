"""Reconciliation engine for the semantic-search indexer.

The :class:`Reconciler` facade drives the two operations the daemon loop calls
in turn: the watermark-driven incremental sync and the deletion sweep.
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
