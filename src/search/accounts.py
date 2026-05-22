"""Account-management guards for the search server (web-redesign §4.6).

The user-CRUD endpoints (``PATCH``/``DELETE /api/users/{id}``) enforce two
safety rules so an admin cannot lock the deployment out of administration:

- **No self-foot-gun.** A user cannot delete themselves, suspend themselves,
  or demote themselves out of the admin role.
- **Never zero admins.** The last *active* admin cannot be deleted,
  suspended, or demoted — there must always be at least one admin who can
  sign in and administer the system.

:func:`guard_delete` and :func:`guard_update` raise :class:`GuardError` when a
requested change would breach a rule; the route layer turns that into a
``409 Conflict``. The guards read live counts from ``app.db`` so the
last-admin check reflects the database, not a stale snapshot.

Allowed deps: sqlite3, appdb.users. Forbidden: FastAPI, store, daemons.
"""

from __future__ import annotations

import sqlite3

from appdb import users as user_store


class GuardError(Exception):
    """Raised when an account change would breach a safety rule.

    Carries a human-readable message explaining which rule was hit (deleting
    yourself, removing the last admin, etc.). The route layer maps it to a
    ``409 Conflict`` response with that message as the ``detail``.
    """


def _is_demotion_from_admin(
    conn: sqlite3.Connection, target_id: int, new_role: str | None
) -> bool:
    """Return whether *new_role* demotes *target_id* out of the admin role.

    A demotion only when the target is currently an admin and *new_role* is a
    supplied, non-admin role.

    Args:
        conn: An open ``app.db`` connection.
        target_id: The id of the user being changed.
        new_role: The requested new role, or ``None`` when role is unchanged.
    """
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
    """Return whether removing *target_id*'s admin-ness empties the admin set.

    *removes_admin* is ``True`` when the operation deletes, suspends, or
    demotes the target. The operation empties the admin set when the target
    is currently an active admin and they are the only active admin.

    Args:
        conn: An open ``app.db`` connection.
        target_id: The id of the user being changed.
        removes_admin: Whether the operation removes the target's ability to
            act as an admin.
    """
    if not removes_admin:
        return False
    target = user_store.get_by_id(conn, target_id)
    if target is None or target.role != "admin" or target.status != "active":
        # The target is not an active admin, so removing them cannot empty
        # the active-admin set.
        return False
    # The target is one active admin; the operation is unsafe only if they
    # are the *only* active admin.
    return user_store.count_admins(conn) <= 1


def guard_delete(conn: sqlite3.Connection, *, target_id: int, actor_id: int) -> None:
    """Raise :class:`GuardError` if deleting *target_id* is unsafe.

    Unsafe when the actor is deleting themselves, or when the target is the
    last active admin.

    Args:
        conn: An open ``app.db`` connection.
        target_id: The id of the user to be deleted.
        actor_id: The id of the admin performing the deletion.

    Raises:
        GuardError: The deletion would breach a safety rule.
    """
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
    role nor status (e.g. a display-name edit) is always allowed, including
    on oneself.

    Args:
        conn: An open ``app.db`` connection.
        target_id: The id of the user being updated.
        actor_id: The id of the admin performing the update.
        new_role: The requested new role, or ``None`` when unchanged.
        new_status: The requested new status, or ``None`` when unchanged.

    Raises:
        GuardError: The update would breach a safety rule.
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
