"""Shared fixtures and mock builders for the indexer unit tests.

``make_reconciler_paperless`` is re-exported from :mod:`tests.helpers.mocks` so
the reconciler test files import everything from one place.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

import common.shutdown as shutdown_mod
from indexer.reconciler import Reconciler, SyncReport
from indexer.worker import IndexOutcome
from store.models import IndexState
from tests.helpers.factories import make_settings_obj
from tests.helpers.mocks import make_mock_embedding_client, make_reconciler_paperless

__all__ = [
    "always_indexed",
    "make_daemon_reconciler",
    "make_daemon_settings",
    "make_reconciler_paperless",
    "make_reconciler_store_writer",
    "run_incremental_sync",
]


@pytest.fixture(autouse=True)
def _reset_shutdown() -> Iterator[None]:
    """Reset the process-global shutdown flag so it cannot leak between tests."""
    shutdown_mod.reset_shutdown()
    yield
    shutdown_mod.reset_shutdown()


def make_reconciler_store_writer(
    *,
    watermark: str | None = None,
    index_state: dict[int, IndexState] | None = None,
    store_ids: set[int] | None = None,
) -> MagicMock:
    """Return a mock StoreWriter with a working in-memory meta table.

    ``read_meta`` / ``write_meta`` are backed by a dict exposed as ``_meta`` so
    tests can assert on what the reconciler persisted.
    """
    store_writer = MagicMock()
    meta: dict[str, str] = {}
    if watermark is not None:
        meta["modified_watermark"] = watermark
    store_writer.read_meta.side_effect = lambda key: meta.get(key)
    store_writer.write_meta.side_effect = lambda key, value: meta.__setitem__(
        key, value
    )
    store_writer._meta = meta  # exposed for assertions
    store_writer.get_index_state.return_value = index_state or {}
    store_writer.get_all_document_ids.return_value = store_ids or set()
    return store_writer


def always_indexed(
    _self: object, doc: dict, existing: IndexState | None
) -> IndexOutcome:
    """A ``DocumentIndexer.index_document`` stub that indexes every document."""
    return IndexOutcome.INDEXED


def run_incremental_sync(paperless: MagicMock, store_writer: MagicMock) -> SyncReport:
    """Construct a Reconciler over the mocks with default settings and run one sync."""
    return Reconciler(
        make_settings_obj(), paperless, store_writer, make_mock_embedding_client()
    ).incremental_sync()


def make_daemon_reconciler() -> MagicMock:
    """Return a mock Reconciler whose two operations report empty outcomes."""
    reconciler = MagicMock()
    reconciler.incremental_sync.return_value = MagicMock(
        indexed=0, metadata_only=0, skipped=0, failed=0, given_up=0
    )
    reconciler.deletion_sweep.return_value = MagicMock(
        pruned=0, aborted=False, candidates=0
    )
    return reconciler


def make_daemon_settings(
    reconcile_interval: int = 300, deletion_sweep_interval: int = 3600
) -> MagicMock:
    """Return a MagicMock standing in for Settings with the loop intervals."""
    settings = MagicMock()
    settings.RECONCILE_INTERVAL = reconcile_interval
    settings.DELETION_SWEEP_INTERVAL = deletion_sweep_interval
    return settings
