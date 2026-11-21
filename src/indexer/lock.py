"""Single-writer lock for the indexer daemon.

Only one indexer process may write to the store at a time. The lock is an
exclusive flock on ``<db_path>.lock``, held for the process lifetime.
"""

from __future__ import annotations

import fcntl
import typing


class IndexerLockError(Exception):
    """Raised when another indexer process already holds the writer lock."""


def acquire_writer_lock(db_path: str) -> typing.IO[bytes]:
    """Take a non-blocking exclusive flock on ``<db_path>.lock``.

    The caller must keep the returned handle open to hold the lock; closing it
    releases the lock.

    Raises:
        IndexerLockError: if another process already holds the lock.
    """
    lock_path = db_path + ".lock"
    handle: typing.IO[bytes] = open(lock_path, "wb")  # noqa: SIM115 — intentional long-lived open
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise IndexerLockError(
            f"Cannot acquire exclusive writer lock on {lock_path!r}: "
            "another indexer process is already running."
        ) from exc
    return handle
