"""Account-management guards for the search server (web-redesign §4.6).

The user-CRUD endpoints (``PATCH``/``DELETE /api/users/{id}``) enforce two
safety rules so an admin cannot lock the deployment out of administration:

- **No self-foot-gun.** A user cannot delete themselves, suspend themselves,
  or demote themselves out of the admin role.
- **Never zero admins.** The last *active* admin cannot be deleted,
  suspended, or demoted — there must always be at least one admin who can
  sign in and administer the system.

:func:`guard_delete` and :func:`guard_update` are the pure predicate checks —
they read live counts and raise :class:`GuardError` when a requested change
would breach a rule.

:func:`apply_guarded_delete` and :func:`apply_guarded_update` are how the
route handlers actually mutate a user: they run the guard read **and** the
mutating write inside one ``BEGIN IMMEDIATE`` transaction. Without that, the
guard is a read-then-write TOCTOU — two concurrent requests demoting the two
remaining admins could both pass ``count_admins() > 1`` and leave zero admins,
an unrecoverable lockout. Under the shared transaction the second writer
blocks on SQLite's write lock until the first commits, then re-reads the count
and sees the first writer's effect.

Allowed deps: sqlite3, appdb (connection, users, sessions), search.errors.
Forbidden: FastAPI, store, daemons.
"""

from __future__ import annotations

import sqlite3

from appdb import sessions as session_store
from appdb import users as user_store
from appdb.connection import transaction
from appdb.users import Role, User, UserStatus
from search.errors import RowVanishedError


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
    last active admin. This is the pure check; :func:`apply_guarded_delete`
    runs it atomically with the delete.

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
    on oneself. This is the pure check; :func:`apply_guarded_update` runs it
    atomically with the update.

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


def apply_guarded_delete(
    conn: sqlite3.Connection, *, target_id: int, actor_id: int
) -> None:
    """Delete *target_id*, with the last-admin/self guard applied atomically.

    The guard read (``count_admins``) and the ``DELETE`` run inside one
    ``BEGIN IMMEDIATE`` transaction, so a concurrent delete/demote/suspend of
    another admin serialises behind SQLite's write lock and the guard here
    sees its committed effect — two races cannot both empty the admin set.

    Args:
        conn: An open ``app.db`` connection.
        target_id: The id of the user to delete.
        actor_id: The id of the admin performing the deletion.

    Raises:
        GuardError: The deletion would breach a safety rule; nothing is
            written and the transaction is rolled back.
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
    """Apply a partial update to *target_id*, guarded atomically.

    The guard read and the ``UPDATE`` run inside one ``BEGIN IMMEDIATE``
    transaction (see :func:`apply_guarded_delete` for why) — that atomicity is
    what makes the last-admin invariant race-free.

    When the update suspends the user, every session they hold is then deleted
    so access is revoked immediately (spec §4.4). That session sweep is a
    committed follow-on, not part of the guarded transaction; it does not need
    to be, because :func:`~search.sessions.resolve_session` already fails
    closed on a ``suspended`` user, so the suspension takes effect the instant
    the ``UPDATE`` commits regardless of whether the session rows are gone yet.

    The caller must have already confirmed *target_id* exists (the route
    layer's 404 check); this function asserts the row is present after the
    update rather than returning ``None``.

    Args:
        conn: An open ``app.db`` connection.
        target_id: The id of the user to update.
        actor_id: The id of the admin performing the update.
        display_name: A new display name, or ``None`` to leave it.
        email: A new email, or ``None`` to leave it.
        role: A new role, or ``None`` to leave it.
        status: A new status, or ``None`` to leave it.
        password_hash: A new argon2id hash, or ``None`` to leave it.

    Returns:
        The updated :class:`~appdb.users.User`.

    Raises:
        GuardError: The update would breach a safety rule; nothing is written
            and the transaction is rolled back.
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
    # The caller's 404 check passed and this is the only writer for the row
    # within the transaction — the update matched a row. An explicit raise
    # (not an `assert`, which `python -O` strips — §17.2) makes a row that
    # vanished mid-transaction fail loud here rather than as a later
    # AttributeError.
    if updated is None:
        raise RowVanishedError(f"user {target_id} vanished during a guarded update")
    # Suspending a user revokes their access immediately: drop every session
    # they hold (spec §4.4). A committed follow-on — see the docstring.
    if status == "suspended":
        session_store.delete_for_user(conn, target_id)
    return updated
