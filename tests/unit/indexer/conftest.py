"""Shared fixtures and mock builders for the indexer unit tests.

The reconciler's tests are split across several files mirroring the
``indexer/reconciler/`` package (CODE_GUIDELINES §11.2); the StoreWriter mock
builder, the construct-and-run helper, and the common ``index_document`` stub
they all share live here so each test file imports one definition rather than
redeclaring it.  The Paperless mock builder lives in :mod:`tests.helpers.mocks`
(the reconciler integration tests share it too) and is re-exported here so the
reconciler unit test files import everything from one place.
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
    "make_reconciler_paperless",
    "make_reconciler_store_writer",
    "run_incremental_sync",
]


@pytest.fixture(autouse=True)
def _reset_shutdown() -> Iterator[None]:
    """Clear the process-global shutdown flag before and after each test.

    The daemon's shutdown signal is a process-global; without this reset a test
    that requests shutdown would leak the flag into the next test.
    """
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

    Args:
        watermark: Initial ``modified_watermark`` meta value, if any.
        index_state: The mapping ``get_index_state`` returns.
        store_ids: The id set ``get_all_document_ids`` returns.
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
    """A DocumentIndexer.index_document stub that indexes every document.

    The common case for reconciler tests exercising watermark and taxonomy
    behaviour rather than per-document worker outcomes.  Usable directly as a
    ``monkeypatch.setattr`` value for the method.
    """
    return IndexOutcome.INDEXED


def run_incremental_sync(paperless: MagicMock, store_writer: MagicMock) -> SyncReport:
    """Construct a Reconciler over the mocks and run one incremental_sync.

    Settings and the embedding client are the shared factory defaults; the
    reconciler holds no state worth keeping past the call, so this collapses
    the construct-and-run boilerplate every incremental-sync test repeats.
    """
    return Reconciler(
        make_settings_obj(), paperless, store_writer, make_mock_embedding_client()
    ).incremental_sync()
