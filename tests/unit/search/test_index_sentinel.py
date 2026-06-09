"""Tests for search.index_sentinel.request_index_rebuild."""

from __future__ import annotations

import pytest

from search.index_sentinel import (
    RECONCILE_SENTINEL_NAME,
    REBUILD_SENTINEL_NAME,
    request_index_rebuild,
)


def test_request_index_rebuild_writes_both_sentinels(tmp_path) -> None:
    """It drops rebuild.request and reconcile.request beside index.db."""
    request_index_rebuild(str(tmp_path / "index.db"))
    assert (tmp_path / REBUILD_SENTINEL_NAME).exists()
    assert (tmp_path / RECONCILE_SENTINEL_NAME).exists()


def test_request_index_rebuild_is_idempotent(tmp_path) -> None:
    """Calling twice is fine — touching an existing sentinel is a no-op."""
    request_index_rebuild(str(tmp_path / "index.db"))
    request_index_rebuild(str(tmp_path / "index.db"))
    assert (tmp_path / REBUILD_SENTINEL_NAME).exists()


def test_request_index_rebuild_raises_when_data_dir_missing(tmp_path) -> None:
    """A missing data directory surfaces as OSError for the caller to translate
    (the routes turn it into a 503 / a logged best-effort failure)."""
    with pytest.raises(OSError):
        request_index_rebuild(str(tmp_path / "does-not-exist" / "index.db"))
