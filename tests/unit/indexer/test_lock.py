"""Tests for the single-writer flock guard (src/indexer/lock.py).

Verifies the three behavioural promises:
- A first acquire on a path succeeds and returns a file handle.
- A second acquire on the same path raises IndexerLockError while the first holds.
- Closing the first handle releases the lock so a subsequent acquire succeeds.
"""
from __future__ import annotations

import pytest

from indexer.lock import IndexerLockError, acquire_writer_lock


def test_first_acquire_returns_file_handle(tmp_path: pytest.TempPathFactory) -> None:
    """A successful acquire returns an open file object."""
    db_path = str(tmp_path / "index.db")
    handle = acquire_writer_lock(db_path)
    try:
        assert handle is not None
        assert not handle.closed
    finally:
        handle.close()


def test_second_acquire_raises_while_first_held(tmp_path: pytest.TempPathFactory) -> None:
    """Acquiring the same lock a second time raises IndexerLockError."""
    db_path = str(tmp_path / "index.db")
    first = acquire_writer_lock(db_path)
    try:
        with pytest.raises(IndexerLockError) as exc_info:
            acquire_writer_lock(db_path)
        # The error message should name the lock path so the operator can diagnose.
        assert str(tmp_path / "index.db") + ".lock" in str(exc_info.value)
    finally:
        first.close()


def test_acquire_succeeds_after_releasing_previous_lock(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Releasing the first lock allows a subsequent acquire to succeed."""
    db_path = str(tmp_path / "index.db")
    first = acquire_writer_lock(db_path)
    first.close()

    second = acquire_writer_lock(db_path)
    try:
        assert not second.closed
    finally:
        second.close()
