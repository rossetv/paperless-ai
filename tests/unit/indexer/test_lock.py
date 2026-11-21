"""Tests for the indexer's single-writer flock guard."""

from __future__ import annotations

import pytest

from indexer.lock import IndexerLockError, acquire_writer_lock


def test_first_acquire_returns_file_handle(tmp_path: pytest.TempPathFactory) -> None:
    db_path = str(tmp_path / "index.db")
    handle = acquire_writer_lock(db_path)
    try:
        assert handle is not None
        assert not handle.closed
    finally:
        handle.close()


def test_second_acquire_raises_while_first_held(
    tmp_path: pytest.TempPathFactory,
) -> None:
    db_path = str(tmp_path / "index.db")
    first = acquire_writer_lock(db_path)
    try:
        with pytest.raises(IndexerLockError) as exc_info:
            acquire_writer_lock(db_path)
        # The message names the lock path so the operator can diagnose.
        assert str(tmp_path / "index.db") + ".lock" in str(exc_info.value)
    finally:
        first.close()


def test_acquire_succeeds_after_releasing_previous_lock(
    tmp_path: pytest.TempPathFactory,
) -> None:
    db_path = str(tmp_path / "index.db")
    first = acquire_writer_lock(db_path)
    first.close()

    second = acquire_writer_lock(db_path)
    try:
        assert not second.closed
    finally:
        second.close()
