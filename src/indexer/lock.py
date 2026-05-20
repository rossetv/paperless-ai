"""Single-writer lock for the indexer daemon.

Enforces the single-writer invariant described in the design spec (§3.2 and §9.1):
only one indexer process may write to the store at a time.  The lock is an
exclusive OS-level flock on a companion `.lock` file beside the index database.

The caller holds the returned file handle open for the process lifetime; closing
it releases the lock.

Depends on: standard library only (fcntl, os).
Forbidden: no sqlite3, no httpx, no store imports.
"""
from __future__ import annotations

import fcntl
import typing


class IndexerLockError(Exception):
    """Raised when the exclusive writer lock cannot be acquired.

    Indicates that another indexer process is already holding the lock.
    The daemon should log this CRITICAL and exit non-zero (CODE_GUIDELINES §1.11).
    """


def acquire_writer_lock(db_path: str) -> typing.IO[bytes]:
    """Open and exclusively flock the companion lock file for *db_path*.

    Opens ``<db_path>.lock`` and takes a non-blocking exclusive flock
    (``LOCK_EX | LOCK_NB``).  Returns the open file object on success; the
    caller must keep it open for the process lifetime to hold the lock.

    Raises:
        IndexerLockError: if another process already holds the lock, with the
            lock-file path in the message so the operator can diagnose.
    """
    lock_path = db_path + ".lock"
    # Open for writing so that the file is created if it does not yet exist.
    handle: typing.IO[bytes] = open(lock_path, "wb")  # noqa: SIM115 — intentional long-lived open
    try:
        # LOCK_EX | LOCK_NB: exclusive, non-blocking.  Raises BlockingIOError
        # immediately if the lock is already held by another process.
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise IndexerLockError(
            f"Cannot acquire exclusive writer lock on {lock_path!r}: "
            "another indexer process is already running."
        ) from exc
    return handle
