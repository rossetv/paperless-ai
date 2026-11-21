"""User accounts, the ``users`` table.

:class:`User` carries ``password_hash`` for the login path; callers serialising
a user for an HTTP response must omit it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

import structlog

from appdb.connection import RowVanishedError, utc_now_iso

log = structlog.get_logger(__name__)

# A Literal makes a typo a type error rather than a row that fails the CHECK.
Role = Literal["admin", "member", "readonly"]

UserStatus = Literal["active", "suspended"]


class UsernameTakenError(Exception):
    """Raised by :func:`create` when the username is already in use.

    Lets the HTTP layer return a clean 409 without string-matching the
    ``sqlite3.IntegrityError`` message.
    """


@dataclass(frozen=True, slots=True)
class User:
    """One row of the ``users`` table, a human account.

    Attributes:
        password_hash: The argon2id encoded hash; never serialise it into an
            HTTP response.
        status: ``active`` or ``suspended``; a suspended user cannot log in.
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


def _row_to_user(row: sqlite3.Row) -> User:
    """Build a :class:`User` from a ``users`` table row."""
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

    The user starts ``active``. Validating *username* is the caller's job;
    *password_hash* comes from :func:`appdb.passwords.hash_password`.

    Raises:
        UsernameTakenError: *username* is already in use.
    """
    now = utc_now_iso()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO users "
                "(username, password_hash, display_name, email, role, status, "
                " created_at, updated_at, last_login_at, password_changed_at) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, NULL, ?)",
                (username, password_hash, display_name, email, role, now, now, now),
            )
    except sqlite3.IntegrityError as exc:
        # The only UNIQUE constraint on users is username.
        raise UsernameTakenError(f"username {username!r} is already in use") from exc
    # The sqlite3 stub declares int | None; a committed INSERT always has an id.
    new_user_id = cursor.lastrowid
    if new_user_id is None:
        raise RowVanishedError(
            "INSERT INTO users succeeded but cursor.lastrowid is None"
        )
    log.info("appdb.user_created", user_id=new_user_id, role=role)
    # Built from the inserted values; no re-SELECT needed.
    return User(
        id=new_user_id,
        username=username,
        password_hash=password_hash,
        display_name=display_name,
        email=email,
        role=role,
        status="active",
        created_at=now,
        updated_at=now,
        last_login_at=None,
        password_changed_at=now,
    )


def get_by_username(conn: sqlite3.Connection, username: str) -> User | None:
    """Return the user with *username*, or ``None`` when no such user exists."""
    row = conn.execute(
        f"SELECT {_USER_COLUMNS} FROM users WHERE username = ?",  # nosec B608 - _USER_COLUMNS is a module constant; username bound via ?
        (username,),
    ).fetchone()
    return _row_to_user(row) if row is not None else None


def get_by_id(conn: sqlite3.Connection, user_id: int) -> User | None:
    """Return the user with *user_id*, or ``None`` when no such user exists."""
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

    A single ``INSERT … SELECT … WHERE NOT EXISTS`` statement is atomic under
    SQLite's write lock, so two concurrent callers cannot both succeed and no
    explicit transaction is needed. Returns ``None`` when a user already exists.
    """
    now = utc_now_iso()
    with conn:
        cursor = conn.execute(
            "INSERT INTO users "
            "(username, password_hash, display_name, email, role, status, "
            " created_at, updated_at, last_login_at, password_changed_at) "
            "SELECT ?, ?, ?, ?, 'admin', 'active', ?, ?, NULL, ? "
            "WHERE NOT EXISTS (SELECT 1 FROM users)",
            (username, password_hash, display_name, email, now, now, now),
        )
    if cursor.rowcount != 1:
        return None
    # The sqlite3 stub declares int | None; a committed INSERT always has an id.
    new_user_id = cursor.lastrowid
    if new_user_id is None:
        raise RowVanishedError(
            "INSERT INTO users (initial admin) succeeded but cursor.lastrowid is None"
        )
    log.info("appdb.initial_admin_created", user_id=new_user_id)
    return User(
        id=new_user_id,
        username=username,
        password_hash=password_hash,
        display_name=display_name,
        email=email,
        role="admin",
        status="active",
        created_at=now,
        updated_at=now,
        last_login_at=None,
        password_changed_at=now,
    )


def list_all(conn: sqlite3.Connection) -> list[User]:
    """Return every user, ordered by id."""
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

    ``None`` means "leave unchanged", so this cannot clear ``display_name`` or
    ``email`` back to NULL. ``updated_at`` always advances, and
    ``password_changed_at`` advances with a new *password_hash*. Returns
    ``None`` when *user_id* does not exist.
    """
    now = utc_now_iso()
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
    with conn:
        cursor = conn.execute(
            f"UPDATE users SET {', '.join(assignments)} WHERE id = ?",  # nosec B608 - assignments are literal "col = ?" fragments built above; values bound via ?
            values,
        )
    if cursor.rowcount == 0:
        return None
    log.info("appdb.user_updated", user_id=user_id)
    return get_by_id(conn, user_id)


def delete(conn: sqlite3.Connection, user_id: int) -> None:
    """Delete the user with *user_id*; a no-op when no such user exists.

    The ``sessions`` foreign key cascades, so their access is revoked at once.
    """
    with conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    log.info("appdb.user_deleted", user_id=user_id)


def count_all(conn: sqlite3.Connection) -> int:
    """Return the total number of users; 0 puts the server into setup mode."""
    row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    return int(row[0])


def count_admins(conn: sqlite3.Connection) -> int:
    """Return the number of *active* admin users.

    A suspended admin cannot act, so the last-admin guard must not count it.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
    ).fetchone()
    return int(row[0])


def record_login(conn: sqlite3.Connection, user_id: int) -> None:
    """Stamp ``last_login_at`` with the current UTC time after a login."""
    with conn:
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (utc_now_iso(), user_id),
        )
