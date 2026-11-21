"""Guards that stop an admin locking the deployment out of administration.

Two rules: a user cannot delete, suspend, or demote themselves, and the last
active admin cannot be deleted, suspended, or demoted.

The ``apply_guarded_*`` functions run the guard read and the write in one
``BEGIN IMMEDIATE`` transaction. Otherwise two concurrent requests demoting the
two remaining admins could both pass ``count_admins() > 1`` and leave zero.
"""

from __future__ import annotations

import sqlite3

from appdb import sessions as session_store
from appdb import users as user_store
from appdb.connection import transaction
from appdb.users import Role, User, UserStatus
from search.errors import RowVanishedError


class GuardError(Exception):
    """An account change would breach a safety rule; the message says which."""


def _is_demotion_from_admin(
    conn: sqlite3.Connection, target_id: int, new_role: str | None
) -> bool:
    """Return whether *new_role* demotes *target_id* out of the admin role."""
    if new_role is None or new_role == "admin":
        return False
    target = user_store.get_by_id(conn, target_id)
    return target is not None and target.role == "admin"


def _would_remove_last_admin(
    conn: sqlite3.Connection,
    target_id: int,
    *,
    removes_admin: bool,
) -> bool:
    """Return whether the operation would leave no active admin.

    *removes_admin* is ``True`` when the operation deletes, suspends, or
    demotes the target.
    """
    if not removes_admin:
        return False
    target = user_store.get_by_id(conn, target_id)
    if target is None or target.role != "admin" or target.status != "active":
        return False
    return user_store.count_admins(conn) <= 1


def guard_delete(conn: sqlite3.Connection, *, target_id: int, actor_id: int) -> None:
    """Raise :class:`GuardError` if the actor deletes themselves or the last admin."""
    if target_id == actor_id:
        raise GuardError("You cannot delete yourself.")
    if _would_remove_last_admin(conn, target_id, removes_admin=True):
        raise GuardError("You cannot delete the last remaining admin.")


def guard_update(
    conn: sqlite3.Connection,
    *,
    target_id: int,
    actor_id: int,
    new_role: str | None,
    new_status: str | None,
) -> None:
    """Raise :class:`GuardError` if a role/status change on *target_id* is unsafe.

    Unsafe when the actor suspends or demotes themselves, or when the change
    suspends or demotes the last active admin. A change that touches neither
    role nor status is always allowed, including on oneself.
    """
    suspending = new_status == "suspended"
    demoting = _is_demotion_from_admin(conn, target_id, new_role)
    removes_admin = suspending or demoting

    if target_id == actor_id and removes_admin:
        if suspending:
            raise GuardError("You cannot suspend yourself.")
        raise GuardError("You cannot remove the admin role from yourself.")

    if _would_remove_last_admin(conn, target_id, removes_admin=removes_admin):
        if suspending:
            raise GuardError("You cannot suspend the last remaining admin.")
        raise GuardError("You cannot demote the last remaining admin.")


def apply_guarded_delete(
    conn: sqlite3.Connection, *, target_id: int, actor_id: int
) -> None:
    """Delete *target_id* with the guard applied in the same transaction.

    Raises:
        GuardError: The deletion would breach a safety rule; nothing is written.
    """
    with transaction(conn):
        guard_delete(conn, target_id=target_id, actor_id=actor_id)
        user_store.delete(conn, target_id)


def apply_guarded_update(
    conn: sqlite3.Connection,
    *,
    target_id: int,
    actor_id: int,
    display_name: str | None = None,
    email: str | None = None,
    role: Role | None = None,
    status: UserStatus | None = None,
    password_hash: str | None = None,
) -> User:
    """Apply a partial update to *target_id* with the guard in the same transaction.

    ``None`` fields are left unchanged. Suspending a user also deletes their
    sessions; that runs after the commit, which is safe because
    :func:`~search.sessions.resolve_session` already rejects a suspended user.
    The caller must have confirmed *target_id* exists.

    Raises:
        GuardError: The update would breach a safety rule; nothing is written.
    """
    with transaction(conn):
        guard_update(
            conn,
            target_id=target_id,
            actor_id=actor_id,
            new_role=role,
            new_status=status,
        )
        updated = user_store.update(
            conn,
            target_id,
            display_name=display_name,
            email=email,
            role=role,
            status=status,
            password_hash=password_hash,
        )
    # A raise rather than an assert, which `python -O` strips.
    if updated is None:
        raise RowVanishedError(f"user {target_id} vanished during a guarded update")
    if status == "suspended":
        session_store.delete_for_user(conn, target_id)
    return updated
