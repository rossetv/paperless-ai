"""Queries over the ``api_keys`` table.

The raw key is never stored, only its SHA-256 hex and a display prefix; hashing
and key generation live in :mod:`search.api_keys`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import structlog

from appdb.connection import RowVanishedError, utc_now_iso

log = structlog.get_logger(__name__)


class DuplicateKeyHashError(Exception):
    """Raised by :func:`create` when ``key_hash`` is already in use.

    Lets the caller react to the (astronomically unlikely) hash collision
    without string-matching the ``sqlite3.IntegrityError`` message.
    """


@dataclass(frozen=True, slots=True)
class ApiKey:
    """One row of the ``api_keys`` table.

    Attributes:
        key_hash: SHA-256 hex of the raw key; auth hashes the presented key and
            matches this column.
        key_prefix: The first ~12 characters of the raw key, e.g.
            ``sk-pls-AbC1``; display only, carries no secret.
        owner_user_id: The owning user; deleting the user cascades to the key.
        scopes: A comma-separated subset of ``api``/``mcp``/``admin``.
        expires_at: ISO-8601 UTC expiry, or ``None`` for a non-expiring key.
        request_count: Authenticated requests served, advanced by :func:`touch`.
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


def _row_to_api_key(row: sqlite3.Row) -> ApiKey:
    """Build an :class:`ApiKey` from an ``api_keys`` table row."""
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

    *key_hash* comes from :func:`search.api_keys.hash_key`; *owner_user_id*
    must reference an existing user (the foreign key is enforced). Validating
    *name* is the caller's job.

    Raises:
        DuplicateKeyHashError: *key_hash* is already stored.
    """
    now = utc_now_iso()
    try:
        with conn:
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
    except sqlite3.IntegrityError as exc:
        # The only UNIQUE constraint on api_keys is key_hash.
        raise DuplicateKeyHashError("an API key with this hash already exists") from exc
    # The sqlite3 stub declares int | None; a committed INSERT always has an id.
    new_api_key_id = cursor.lastrowid
    if new_api_key_id is None:
        raise RowVanishedError(
            "INSERT INTO api_keys succeeded but cursor.lastrowid is None"
        )
    log.info(
        "appdb.api_key_created",
        api_key_id=new_api_key_id,
        owner_user_id=owner_user_id,
    )
    # Built from the inserted values; no re-SELECT needed.
    return ApiKey(
        id=new_api_key_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
        owner_user_id=owner_user_id,
        scopes=scopes,
        created_at=now,
        expires_at=expires_at,
        last_used_at=None,
        revoked_at=None,
        request_count=0,
    )


def get_by_hash(conn: sqlite3.Connection, key_hash: str) -> ApiKey | None:
    """Return the key with *key_hash*, or ``None`` when no such key exists.

    The bearer-auth path calls this on every request, so it is indexed by
    ``idx_api_keys_key_hash``.
    """
    row = conn.execute(
        "SELECT id, key_hash, key_prefix, name, owner_user_id, scopes, "
        "created_at, expires_at, last_used_at, revoked_at, request_count "
        "FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    return _row_to_api_key(row) if row is not None else None


def get_by_id(conn: sqlite3.Connection, api_key_id: int) -> ApiKey | None:
    """Return the key with *api_key_id*, or ``None`` when absent."""
    row = conn.execute(
        "SELECT id, key_hash, key_prefix, name, owner_user_id, scopes, "
        "created_at, expires_at, last_used_at, revoked_at, request_count "
        "FROM api_keys WHERE id = ?",
        (api_key_id,),
    ).fetchone()
    return _row_to_api_key(row) if row is not None else None


def list_all(conn: sqlite3.Connection) -> list[ApiKey]:
    """Return every API key, ordered by id."""
    rows = conn.execute(
        "SELECT id, key_hash, key_prefix, name, owner_user_id, scopes, "
        "created_at, expires_at, last_used_at, revoked_at, request_count "
        "FROM api_keys ORDER BY id"
    ).fetchall()
    return [_row_to_api_key(row) for row in rows]


def list_for_user(conn: sqlite3.Connection, owner_user_id: int) -> list[ApiKey]:
    """Return every API key owned by *owner_user_id*, ordered by id."""
    rows = conn.execute(
        "SELECT id, key_hash, key_prefix, name, owner_user_id, scopes, "
        "created_at, expires_at, last_used_at, revoked_at, request_count "
        "FROM api_keys WHERE owner_user_id = ? ORDER BY id",
        (owner_user_id,),
    ).fetchall()
    return [_row_to_api_key(row) for row in rows]


def revoke(conn: sqlite3.Connection, api_key_id: int, *, revoked_at: str) -> None:
    """Mark the key with *api_key_id* revoked; a no-op when it is absent.

    A soft delete: the row stays so the UI can still show the key and its
    usage history. Revoking again overwrites the timestamp.
    """
    with conn:
        conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ?",
            (revoked_at, api_key_id),
        )
    log.info("appdb.api_key_revoked", api_key_id=api_key_id)


def delete(conn: sqlite3.Connection, api_key_id: int) -> None:
    """Hard-delete the key with *api_key_id*; a no-op when it is absent.

    Most callers should prefer :func:`revoke`, which keeps the audit trail.
    """
    with conn:
        conn.execute("DELETE FROM api_keys WHERE id = ?", (api_key_id,))
    log.info("appdb.api_key_deleted", api_key_id=api_key_id)


def touch(conn: sqlite3.Connection, api_key_id: int, *, used_at: str) -> None:
    """Record a use of the key: stamp ``last_used_at`` and bump the count.

    Always writes; the caller throttles it (see
    :func:`search.api_keys.should_touch`) so auth is not a write per request.
    A no-op when *api_key_id* is absent.
    """
    with conn:
        conn.execute(
            "UPDATE api_keys "
            "SET last_used_at = ?, request_count = request_count + 1 "
            "WHERE id = ?",
            (used_at, api_key_id),
        )


# "Not supplied" marker for update(): None is a meaningful expires_at ("never
# expires"), so it cannot double as "leave it".
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

    Arguments left at :data:`_UNSET` are untouched; ``expires_at=None`` clears
    the expiry. With no fields supplied it just re-reads the row. Returns
    ``None`` when *api_key_id* matches no row.
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
        with conn:
            conn.execute(
                f"UPDATE api_keys SET {', '.join(assignments)} WHERE id = ?",  # nosec B608 - assignments are literal "col = ?" fragments built above; values bound via ?
                tuple(params),
            )
        log.info("appdb.api_key_updated", api_key_id=api_key_id)
    return get_by_id(conn, api_key_id)
