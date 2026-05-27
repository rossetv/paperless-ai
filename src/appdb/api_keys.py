"""API keys in the application database — the ``api_keys`` table.

This module owns the :class:`ApiKey` dataclass (one row, fully typed) and
the typed query functions over the ``api_keys`` table. Higher layers — the
search server's bearer-auth path and the key-management endpoints — call
these functions and never write ``api_keys`` SQL themselves.

The raw key is **never** stored: callers store ``key_hash`` (the SHA-256 hex
of the raw key) and ``key_prefix`` (the first ~12 characters, for display).
Hashing and raw-key generation are the search layer's job
(:mod:`search.api_keys`); this module only persists the already-hashed
values.

Allowed deps: sqlite3, structlog. Forbidden: store, search, daemon packages,
FastAPI, hashlib (hashing lives in :mod:`search.api_keys`).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

log = structlog.get_logger(__name__)


class DuplicateKeyHashError(Exception):
    """Raised by :func:`create` when ``key_hash`` is already in use.

    The ``api_keys.key_hash`` column is ``UNIQUE``; a duplicate insert fails
    with ``sqlite3.IntegrityError``. This typed wrapper lets the caller react
    to the (astronomically unlikely) hash collision without string-matching
    the SQLite error message.
    """


@dataclass(frozen=True, slots=True)
class ApiKey:
    """One row of the ``api_keys`` table — a programmatic credential.

    Frozen: a loaded key is a snapshot, never mutated in place; a change goes
    through :func:`revoke` / :func:`touch` and the caller re-fetches.

    Attributes:
        id: The integer primary key.
        key_hash: The SHA-256 hex of the raw key. The raw key is never
            stored; auth hashes the presented key and matches this column.
        key_prefix: The first ~12 characters of the raw key, e.g.
            ``sk-pls-AbC1`` — for display only, carries no secret.
        name: The human label the owner gave the key.
        owner_user_id: The id of the owning user. ``ON DELETE CASCADE`` —
            deleting the user destroys the key.
        scopes: A comma-separated subset of ``api``/``mcp``/``admin``.
        created_at: ISO-8601 UTC creation timestamp.
        expires_at: ISO-8601 UTC expiry, or ``None`` for a non-expiring key.
        last_used_at: ISO-8601 UTC of the last authenticated request, or
            ``None`` if never used.
        revoked_at: ISO-8601 UTC of revocation, or ``None`` if still live.
        request_count: The number of authenticated requests the key has
            served; advanced by the throttled :func:`touch`.
    """

    id: int
    key_hash: str
    key_prefix: str
    name: str
    owner_user_id: int
    scopes: str
    created_at: str
    expires_at: str | None
    last_used_at: str | None
    revoked_at: str | None
    request_count: int


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``+00:00``
    offset — the timestamp format every ``app.db`` table stores."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_api_key(row: sqlite3.Row) -> ApiKey:
    """Build an :class:`ApiKey` from an ``api_keys`` table row.

    The single mapper from a database row to the dataclass, so the column
    mapping lives in exactly one place.
    """
    return ApiKey(
        id=row["id"],
        key_hash=row["key_hash"],
        key_prefix=row["key_prefix"],
        name=row["name"],
        owner_user_id=row["owner_user_id"],
        scopes=row["scopes"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        last_used_at=row["last_used_at"],
        revoked_at=row["revoked_at"],
        request_count=row["request_count"],
    )


# The column list shared by every SELECT, so a schema change is a one-line
# edit. Ordered to match _row_to_api_key (which indexes by name).
_API_KEY_COLUMNS = (
    "id, key_hash, key_prefix, name, owner_user_id, scopes, created_at, "
    "expires_at, last_used_at, revoked_at, request_count"
)


def create(
    conn: sqlite3.Connection,
    *,
    key_hash: str,
    key_prefix: str,
    name: str,
    owner_user_id: int,
    scopes: str,
    expires_at: str | None = None,
) -> ApiKey:
    """Insert a new API key and return it fully populated.

    ``created_at`` is set to the current UTC time; ``request_count`` starts
    at 0; ``last_used_at`` and ``revoked_at`` start ``NULL``. The insert is
    committed before the row is re-read.

    Args:
        conn: An open, migrated ``app.db`` connection.
        key_hash: The SHA-256 hex of the raw key (from
            :func:`search.api_keys.hash_key`).
        key_prefix: The display prefix of the raw key.
        name: The human label for the key. Validation is the caller's job.
        owner_user_id: The id of the owning user. Must reference an existing
            ``users`` row — the foreign key is enforced.
        scopes: A comma-separated scope string.
        expires_at: An optional ISO-8601 UTC expiry; ``None`` never expires.

    Returns:
        The created :class:`ApiKey`.

    Raises:
        DuplicateKeyHashError: *key_hash* is already stored.
    """
    now = _utc_now_iso()
    try:
        cursor = conn.execute(
            "INSERT INTO api_keys "
            "(key_hash, key_prefix, name, owner_user_id, scopes, "
            " created_at, expires_at, last_used_at, revoked_at, "
            " request_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0)",
            (
                key_hash,
                key_prefix,
                name,
                owner_user_id,
                scopes,
                now,
                expires_at,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        # The only UNIQUE constraint on api_keys is key_hash.
        raise DuplicateKeyHashError("an API key with this hash already exists") from exc
    # A successful single-row INSERT always sets lastrowid; the assert narrows
    # the int | None the sqlite3 stub declares so the type checker is satisfied.
    new_api_key_id = cursor.lastrowid
    assert new_api_key_id is not None
    log.info(
        "appdb.api_key_created",
        api_key_id=new_api_key_id,
        owner_user_id=owner_user_id,
    )
    created = get_by_id(conn, new_api_key_id)
    # The row was just inserted on this connection — it must be present.
    assert created is not None
    return created


def get_by_hash(conn: sqlite3.Connection, key_hash: str) -> ApiKey | None:
    """Return the key with *key_hash*, or ``None`` when no such key exists.

    The lookup the bearer-auth path performs on every request: hash the
    presented key, then call this. Indexed by ``idx_api_keys_key_hash``.

    Args:
        conn: An open ``app.db`` connection.
        key_hash: The SHA-256 hex to look up.
    """
    row = conn.execute(
        f"SELECT {_API_KEY_COLUMNS} FROM api_keys WHERE key_hash = ?",  # nosec B608 - _API_KEY_COLUMNS is a module constant; key_hash bound via ?
        (key_hash,),
    ).fetchone()
    return _row_to_api_key(row) if row is not None else None


def get_by_id(conn: sqlite3.Connection, api_key_id: int) -> ApiKey | None:
    """Return the key with *api_key_id*, or ``None`` when absent.

    Used by :func:`create` to re-read the freshly inserted row, and by the
    CRUD endpoints to resolve a key for revoke/delete.

    Args:
        conn: An open ``app.db`` connection.
        api_key_id: The integer primary key to look up.
    """
    row = conn.execute(
        f"SELECT {_API_KEY_COLUMNS} FROM api_keys WHERE id = ?",  # nosec B608 - _API_KEY_COLUMNS is a module constant; api_key_id bound via ?
        (api_key_id,),
    ).fetchone()
    return _row_to_api_key(row) if row is not None else None


def list_all(conn: sqlite3.Connection) -> list[ApiKey]:
    """Return every API key, ordered by ascending id.

    Backs ``GET /api/api-keys`` for an admin caller.

    Args:
        conn: An open ``app.db`` connection.

    Returns:
        A list of every :class:`ApiKey`; empty when none exist.
    """
    rows = conn.execute(
        f"SELECT {_API_KEY_COLUMNS} FROM api_keys ORDER BY id"  # nosec B608 - _API_KEY_COLUMNS is a module constant; no caller input in SQL
    ).fetchall()
    return [_row_to_api_key(row) for row in rows]


def list_for_user(conn: sqlite3.Connection, owner_user_id: int) -> list[ApiKey]:
    """Return every API key owned by *owner_user_id*, ordered by id.

    Backs ``GET /api/api-keys`` for a non-admin caller, who sees only their
    own keys.

    Args:
        conn: An open ``app.db`` connection.
        owner_user_id: The owning user's id.

    Returns:
        The owner's :class:`ApiKey` list; empty when they have none.
    """
    rows = conn.execute(
        f"SELECT {_API_KEY_COLUMNS} FROM api_keys WHERE owner_user_id = ? ORDER BY id",  # nosec B608 - _API_KEY_COLUMNS is a module constant; owner_user_id bound via ?
        (owner_user_id,),
    ).fetchall()
    return [_row_to_api_key(row) for row in rows]


def revoke(conn: sqlite3.Connection, api_key_id: int, *, revoked_at: str) -> None:
    """Mark the key with *api_key_id* revoked; a no-op when it is absent.

    Sets ``revoked_at`` to *revoked_at*. Revocation is a soft delete: the row
    stays so the UI can still show the key as revoked and its usage history.
    Calling this on an already-revoked key simply overwrites the timestamp —
    it never raises.

    Args:
        conn: An open ``app.db`` connection.
        api_key_id: The id of the key to revoke.
        revoked_at: The ISO-8601 UTC revocation timestamp.
    """
    conn.execute(
        "UPDATE api_keys SET revoked_at = ? WHERE id = ?",
        (revoked_at, api_key_id),
    )
    conn.commit()
    log.info("appdb.api_key_revoked", api_key_id=api_key_id)


def delete(conn: sqlite3.Connection, api_key_id: int) -> None:
    """Hard-delete the key with *api_key_id*; a no-op when it is absent.

    Permanently removes the row, history and all. Most callers should prefer
    :func:`revoke`, which keeps the audit trail; ``delete`` exists for an
    explicit "forget this key entirely" action.

    Args:
        conn: An open ``app.db`` connection.
        api_key_id: The id of the key to delete.
    """
    conn.execute("DELETE FROM api_keys WHERE id = ?", (api_key_id,))
    conn.commit()
    log.info("appdb.api_key_deleted", api_key_id=api_key_id)


def touch(conn: sqlite3.Connection, api_key_id: int, *, used_at: str) -> None:
    """Record a use of the key: stamp ``last_used_at`` and bump the count.

    Sets ``last_used_at`` to *used_at* and increments ``request_count`` by
    one, in a single statement. A no-op when *api_key_id* is absent.

    The *caller* throttles how often this is invoked (see
    :func:`search.api_keys.should_touch`) so authentication is not a database
    write on every request — this function itself always writes.

    Args:
        conn: An open ``app.db`` connection.
        api_key_id: The id of the key that served a request.
        used_at: The ISO-8601 UTC timestamp of the request.
    """
    conn.execute(
        "UPDATE api_keys "
        "SET last_used_at = ?, request_count = request_count + 1 "
        "WHERE id = ?",
        (used_at, api_key_id),
    )
    conn.commit()


# Sentinel for "this field was not supplied" in update(). expires_at is
# nullable — None there is a meaningful value ("never expires") — so a
# distinct sentinel is needed to tell "set expiry to null" from "leave it".
_UNSET: object = object()


def update(
    conn: sqlite3.Connection,
    api_key_id: int,
    *,
    name: str | object = _UNSET,
    scopes: str | object = _UNSET,
    expires_at: str | None | object = _UNSET,
) -> ApiKey | None:
    """Edit a key's mutable fields; return the updated row, or ``None``.

    Only the supplied fields are changed — any argument left at :data:`_UNSET`
    is untouched. ``name`` and ``scopes`` are non-nullable; ``expires_at``
    accepts ``None`` to clear an expiry (passing ``None`` is distinct from
    omitting the argument, hence the sentinel). The immutable fields
    (``key_hash``, ``key_prefix``, ``owner_user_id``, ``created_at``) and the
    usage counters can never be edited here.

    Returns ``None`` when *api_key_id* matches no row, so the caller can map
    that to a 404. With no fields supplied it is a no-op that simply re-reads
    and returns the current row.

    Args:
        conn: An open ``app.db`` connection.
        api_key_id: The id of the key to edit.
        name: A new human label, or :data:`_UNSET` to leave it.
        scopes: A new comma-separated scope string, or :data:`_UNSET`.
        expires_at: A new ISO-8601 UTC expiry, ``None`` to clear the expiry,
            or :data:`_UNSET` to leave it.

    Returns:
        The updated :class:`ApiKey`, or ``None`` when no such key exists.
    """
    assignments: list[str] = []
    params: list[str | None] = []
    if name is not _UNSET:
        assignments.append("name = ?")
        params.append(name)  # type: ignore[arg-type]
    if scopes is not _UNSET:
        assignments.append("scopes = ?")
        params.append(scopes)  # type: ignore[arg-type]
    if expires_at is not _UNSET:
        assignments.append("expires_at = ?")
        params.append(expires_at)  # type: ignore[arg-type]

    if assignments:
        params.append(api_key_id)  # type: ignore[arg-type]
        conn.execute(
            f"UPDATE api_keys SET {', '.join(assignments)} WHERE id = ?",  # nosec B608 - assignments are literal "col = ?" fragments built above; values bound via ?
            tuple(params),
        )
        conn.commit()
        log.info("appdb.api_key_updated", api_key_id=api_key_id)
    return get_by_id(conn, api_key_id)
