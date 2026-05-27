"""User accounts in the application database — the ``users`` table.

This module owns the :class:`User` dataclass (one row, fully typed) and the
typed query functions over the ``users`` table. Higher layers (the search
server's auth and admin endpoints) call these functions and never write SQL
themselves — appdb is the only place ``app.db`` SQL is built.

The :class:`User` dataclass carries ``password_hash`` because the login path
needs it; callers serialising a user for an HTTP response must omit it.

Allowed deps: sqlite3, structlog. Forbidden: store, search, daemon packages,
FastAPI, argon2 (hashing lives in :mod:`appdb.passwords`).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

# The three human-account roles (spec §4.3). A Literal makes a typo a type
# error at every call site rather than a row that fails the CHECK constraint.
Role = Literal["admin", "member", "readonly"]

# The two account statuses (spec §4.2).
UserStatus = Literal["active", "suspended"]


class UsernameTakenError(Exception):
    """Raised by :func:`create` when the username is already in use.

    The ``users.username`` column is ``UNIQUE``; a duplicate insert fails
    with ``sqlite3.IntegrityError``. This typed wrapper lets the HTTP layer
    return a clean 409 without string-matching the SQLite error message.
    """


@dataclass(frozen=True, slots=True)
class User:
    """One row of the ``users`` table — a human account (spec §4.2).

    Frozen: a loaded user is a snapshot, never mutated in place; an update
    goes through :func:`update` and the caller re-fetches.

    Attributes:
        id: The integer primary key.
        username: The unique login name.
        password_hash: The argon2id encoded password hash. Present for the
            login path; never serialise it into an HTTP response.
        display_name: The optional human-friendly name, or ``None``.
        email: The optional email address, or ``None``.
        role: One of ``admin`` / ``member`` / ``readonly``.
        status: ``active`` or ``suspended``; a suspended user cannot log in.
        created_at: ISO-8601 UTC creation timestamp.
        updated_at: ISO-8601 UTC last-modification timestamp.
        last_login_at: ISO-8601 UTC last successful login, or ``None``.
        password_changed_at: ISO-8601 UTC last password change, or ``None``.
    """

    id: int
    username: str
    password_hash: str
    display_name: str | None
    email: str | None
    role: Role
    status: UserStatus
    created_at: str
    updated_at: str
    last_login_at: str | None
    password_changed_at: str | None


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``+00:00``
    offset — the timestamp format every ``app.db`` table stores."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_user(row: sqlite3.Row) -> User:
    """Build a :class:`User` from a ``users`` table row.

    The single mapper from a database row to the dataclass, so the column
    order lives in exactly one place.
    """
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        display_name=row["display_name"],
        email=row["email"],
        role=row["role"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_login_at=row["last_login_at"],
        password_changed_at=row["password_changed_at"],
    )


# The column list shared by every SELECT, so a schema change is a one-line
# edit. Ordered to match _row_to_user (which indexes by name, so order is for
# readers only).
_USER_COLUMNS = (
    "id, username, password_hash, display_name, email, role, status, "
    "created_at, updated_at, last_login_at, password_changed_at"
)


def create(
    conn: sqlite3.Connection,
    *,
    username: str,
    password_hash: str,
    role: Role,
    display_name: str | None = None,
    email: str | None = None,
) -> User:
    """Insert a new user and return it fully populated.

    ``created_at``, ``updated_at`` and ``password_changed_at`` are set to the
    current UTC time; ``status`` defaults to ``active`` and ``last_login_at``
    to ``None``. The insert is committed before the row is re-read.

    Args:
        conn: An open, migrated ``app.db`` connection.
        username: The unique login name. Validation (length, charset) is the
            caller's responsibility.
        password_hash: An argon2id hash from :func:`appdb.passwords.hash_password`.
        role: The account role.
        display_name: An optional display name.
        email: An optional email address.

    Returns:
        The created :class:`User`.

    Raises:
        UsernameTakenError: *username* is already in use.
    """
    now = _utc_now_iso()
    try:
        cursor = conn.execute(
            "INSERT INTO users "
            "(username, password_hash, display_name, email, role, status, "
            " created_at, updated_at, last_login_at, password_changed_at) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, NULL, ?)",
            (username, password_hash, display_name, email, role, now, now, now),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        # The only UNIQUE constraint on users is username.
        raise UsernameTakenError(f"username {username!r} is already in use") from exc
    # A successful single-row INSERT always sets lastrowid; the assert narrows
    # the int | None the sqlite3 stub declares so the type checker is satisfied.
    new_user_id = cursor.lastrowid
    assert new_user_id is not None
    log.info("appdb.user_created", user_id=new_user_id, role=role)
    created = get_by_id(conn, new_user_id)
    # The row was just inserted in this connection — it must be present.
    assert created is not None
    return created


def get_by_username(conn: sqlite3.Connection, username: str) -> User | None:
    """Return the user with *username*, or ``None`` when no such user exists.

    Args:
        conn: An open ``app.db`` connection.
        username: The login name to look up.
    """
    row = conn.execute(
        f"SELECT {_USER_COLUMNS} FROM users WHERE username = ?",  # nosec B608 - _USER_COLUMNS is a module constant; username bound via ?
        (username,),
    ).fetchone()
    return _row_to_user(row) if row is not None else None


def get_by_id(conn: sqlite3.Connection, user_id: int) -> User | None:
    """Return the user with *user_id*, or ``None`` when no such user exists.

    Args:
        conn: An open ``app.db`` connection.
        user_id: The integer primary key to look up.
    """
    row = conn.execute(
        f"SELECT {_USER_COLUMNS} FROM users WHERE id = ?",  # nosec B608 - _USER_COLUMNS is a module constant; user_id bound via ?
        (user_id,),
    ).fetchone()
    return _row_to_user(row) if row is not None else None


def create_initial_admin(
    conn: sqlite3.Connection,
    *,
    username: str,
    password_hash: str,
    display_name: str | None = None,
    email: str | None = None,
) -> User | None:
    """Insert the first-ever admin account, atomically — or do nothing.

    Executes a single ``INSERT … SELECT … WHERE NOT EXISTS`` statement. SQLite
    evaluates the ``WHERE NOT EXISTS (SELECT 1 FROM users)`` sub-query and the
    insert as one atomic operation under its write lock, so two concurrent
    callers cannot both succeed: the second sees a non-empty table inside the
    same statement and inserts zero rows.

    Because this is a single statement it is correct regardless of the
    connection's ``isolation_level`` setting — no ``BEGIN IMMEDIATE`` or manual
    transaction management is needed.

    Args:
        conn: An open, migrated ``app.db`` connection.
        username: The login name for the initial admin.
        password_hash: An argon2id hash from :func:`appdb.passwords.hash_password`.
        display_name: An optional display name.
        email: An optional email address.

    Returns:
        The created :class:`User` when the table was empty and the row was
        inserted; ``None`` when at least one user already existed (i.e.
        ``cursor.rowcount == 0``).
    """
    now = _utc_now_iso()
    cursor = conn.execute(
        "INSERT INTO users "
        "(username, password_hash, display_name, email, role, status, "
        " created_at, updated_at, last_login_at, password_changed_at) "
        "SELECT ?, ?, ?, ?, 'admin', 'active', ?, ?, NULL, ? "
        "WHERE NOT EXISTS (SELECT 1 FROM users)",
        (username, password_hash, display_name, email, now, now, now),
    )
    conn.commit()
    if cursor.rowcount != 1:
        return None
    # The INSERT inserted exactly one row, so lastrowid is set; the assert
    # narrows the int | None the sqlite3 stub declares.
    new_user_id = cursor.lastrowid
    assert new_user_id is not None
    log.info("appdb.initial_admin_created", user_id=new_user_id)
    created = get_by_id(conn, new_user_id)
    # The row was just inserted in this connection — it must be present.
    assert created is not None
    return created


def list_all(conn: sqlite3.Connection) -> list[User]:
    """Return every user, ordered by ascending id.

    Args:
        conn: An open ``app.db`` connection.

    Returns:
        A list of every :class:`User`; empty when no users exist.
    """
    rows = conn.execute(
        f"SELECT {_USER_COLUMNS} FROM users ORDER BY id"  # nosec B608 - _USER_COLUMNS is a module constant; no caller input in SQL
    ).fetchall()
    return [_row_to_user(row) for row in rows]


def update(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    display_name: str | None = None,
    email: str | None = None,
    role: Role | None = None,
    status: UserStatus | None = None,
    password_hash: str | None = None,
) -> User | None:
    """Apply a partial update to a user and return the updated row.

    Only the keyword arguments actually supplied are written; an omitted
    argument leaves that column untouched. ``updated_at`` is always advanced;
    ``password_changed_at`` is advanced only when *password_hash* is supplied.

    **Known Wave-1 limitation — cannot clear a column to NULL.** ``None`` means
    "leave this column unchanged", so it is indistinguishable from omitting the
    argument. A consequence is that ``update`` **cannot blank a previously-set**
    ``display_name`` or ``email`` back to ``NULL``: passing ``email=None`` is a
    no-op, not a clear. This is a deliberate Wave-1 choice — the Wave-1 HTTP
    layer only ever *sets* those optional fields, never clears them. When Wave 3
    adds a Users screen that must support removing an email/display name, this
    function needs an explicit "clear" signal (e.g. a sentinel distinct from
    ``None``, or a separate ``clear_fields`` argument) — a partial ``UPDATE``
    builder keyed solely on ``is None`` cannot express it.

    Args:
        conn: An open ``app.db`` connection.
        user_id: The id of the user to update.
        display_name: A new display name, or ``None`` to leave it.
        email: A new email, or ``None`` to leave it.
        role: A new role, or ``None`` to leave it.
        status: A new status, or ``None`` to leave it.
        password_hash: A new argon2id hash, or ``None`` to leave it.

    Returns:
        The updated :class:`User`, or ``None`` when *user_id* does not exist.
    """
    now = _utc_now_iso()
    # Build the SET clause from only the supplied columns. Column names are
    # fixed literals chosen here — never interpolated user input — and every
    # value is bound as a parameter, so this carries no injection.
    assignments: list[str] = ["updated_at = ?"]
    values: list[object] = [now]
    if display_name is not None:
        assignments.append("display_name = ?")
        values.append(display_name)
    if email is not None:
        assignments.append("email = ?")
        values.append(email)
    if role is not None:
        assignments.append("role = ?")
        values.append(role)
    if status is not None:
        assignments.append("status = ?")
        values.append(status)
    if password_hash is not None:
        assignments.append("password_hash = ?")
        values.append(password_hash)
        assignments.append("password_changed_at = ?")
        values.append(now)

    values.append(user_id)
    cursor = conn.execute(
        f"UPDATE users SET {', '.join(assignments)} WHERE id = ?",  # nosec B608 - assignments are literal "col = ?" fragments built above; values bound via ?
        values,
    )
    conn.commit()
    if cursor.rowcount == 0:
        # No row matched user_id — the user does not exist.
        return None
    log.info("appdb.user_updated", user_id=user_id)
    return get_by_id(conn, user_id)


def delete(conn: sqlite3.Connection, user_id: int) -> None:
    """Delete the user with *user_id*; a no-op when no such user exists.

    The ``sessions`` foreign key cascades, so every session the user holds is
    deleted in the same statement — their access is revoked instantly.

    Args:
        conn: An open ``app.db`` connection.
        user_id: The id of the user to delete.
    """
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    log.info("appdb.user_deleted", user_id=user_id)


def count_all(conn: sqlite3.Connection) -> int:
    """Return the total number of users.

    Used by first-run setup detection: a count of 0 means the server enters
    setup mode.

    Args:
        conn: An open ``app.db`` connection.
    """
    row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    return int(row[0])


def count_admins(conn: sqlite3.Connection) -> int:
    """Return the number of *active* admin users.

    A suspended admin cannot perform any action, so it does not count: the
    last-admin guard must treat "one admin, suspended" as zero live admins.

    Args:
        conn: An open ``app.db`` connection.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
    ).fetchone()
    return int(row[0])


def record_login(conn: sqlite3.Connection, user_id: int) -> None:
    """Stamp ``last_login_at`` with the current UTC time after a login.

    Called from the login handler once the password has verified and the
    session row has been created.

    Args:
        conn: An open ``app.db`` connection.
        user_id: The id of the user who logged in.
    """
    conn.execute(
        "UPDATE users SET last_login_at = ? WHERE id = ?",
        (_utc_now_iso(), user_id),
    )
    conn.commit()
