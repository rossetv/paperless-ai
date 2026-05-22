"""Tests for search.accounts — account operations and guards.

Covers the guard predicates the PATCH/DELETE handlers rely on:
- a user cannot delete or suspend or demote themselves;
- the last remaining admin cannot be deleted, suspended, or demoted;
- a non-self, non-last-admin change is permitted.
And the GuardError they raise.

Also covers the atomic guarded mutators (``apply_guarded_update`` /
``apply_guarded_delete``): the guard read and the write share one
``BEGIN IMMEDIATE`` transaction, so two concurrent demotes cannot both pass
the last-admin check and leave the deployment with zero admins.
"""

from __future__ import annotations

import threading

import pytest

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import count_admins
from appdb.users import create as create_user
from appdb.users import get_by_id
from appdb.users import update as update_user
from search.accounts import (
    GuardError,
    apply_guarded_delete,
    apply_guarded_update,
    guard_delete,
    guard_update,
)


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def test_guard_delete_blocks_deleting_yourself(conn) -> None:
    admin = create_user(conn, username="a", password_hash="h", role="admin")
    create_user(conn, username="b", password_hash="h", role="admin")
    with pytest.raises(GuardError, match="yourself"):
        guard_delete(conn, target_id=admin.id, actor_id=admin.id)


def test_guard_delete_blocks_deleting_the_last_admin(conn) -> None:
    only_admin = create_user(conn, username="a", password_hash="h", role="admin")
    member = create_user(conn, username="b", password_hash="h", role="member")
    with pytest.raises(GuardError, match="last"):
        guard_delete(conn, target_id=only_admin.id, actor_id=member.id)


def test_guard_delete_allows_deleting_a_non_last_admin(conn) -> None:
    actor = create_user(conn, username="a", password_hash="h", role="admin")
    victim = create_user(conn, username="b", password_hash="h", role="admin")
    guard_delete(conn, target_id=victim.id, actor_id=actor.id)  # no raise


def test_guard_delete_allows_deleting_a_member(conn) -> None:
    actor = create_user(conn, username="a", password_hash="h", role="admin")
    member = create_user(conn, username="b", password_hash="h", role="member")
    guard_delete(conn, target_id=member.id, actor_id=actor.id)  # no raise


def test_guard_update_blocks_suspending_yourself(conn) -> None:
    admin = create_user(conn, username="a", password_hash="h", role="admin")
    create_user(conn, username="b", password_hash="h", role="admin")
    with pytest.raises(GuardError, match="yourself"):
        guard_update(
            conn,
            target_id=admin.id,
            actor_id=admin.id,
            new_role=None,
            new_status="suspended",
        )


def test_guard_update_blocks_demoting_yourself(conn) -> None:
    admin = create_user(conn, username="a", password_hash="h", role="admin")
    create_user(conn, username="b", password_hash="h", role="admin")
    with pytest.raises(GuardError, match="yourself"):
        guard_update(
            conn,
            target_id=admin.id,
            actor_id=admin.id,
            new_role="member",
            new_status=None,
        )


def test_guard_update_allows_editing_your_own_display_name(conn) -> None:
    """A self-edit that changes neither role nor status is fine."""
    admin = create_user(conn, username="a", password_hash="h", role="admin")
    guard_update(
        conn,
        target_id=admin.id,
        actor_id=admin.id,
        new_role=None,
        new_status=None,
    )  # no raise


def test_guard_update_blocks_suspending_the_last_admin(conn) -> None:
    only_admin = create_user(conn, username="a", password_hash="h", role="admin")
    member = create_user(conn, username="b", password_hash="h", role="member")
    with pytest.raises(GuardError, match="last"):
        guard_update(
            conn,
            target_id=only_admin.id,
            actor_id=member.id,
            new_role=None,
            new_status="suspended",
        )


def test_guard_update_blocks_demoting_the_last_admin(conn) -> None:
    only_admin = create_user(conn, username="a", password_hash="h", role="admin")
    member = create_user(conn, username="b", password_hash="h", role="member")
    with pytest.raises(GuardError, match="last"):
        guard_update(
            conn,
            target_id=only_admin.id,
            actor_id=member.id,
            new_role="member",
            new_status=None,
        )


def test_guard_update_allows_demoting_a_non_last_admin(conn) -> None:
    actor = create_user(conn, username="a", password_hash="h", role="admin")
    other_admin = create_user(conn, username="b", password_hash="h", role="admin")
    guard_update(
        conn,
        target_id=other_admin.id,
        actor_id=actor.id,
        new_role="member",
        new_status=None,
    )  # no raise — two admins exist


def test_guard_update_allows_promoting_a_member(conn) -> None:
    actor = create_user(conn, username="a", password_hash="h", role="admin")
    member = create_user(conn, username="b", password_hash="h", role="member")
    guard_update(
        conn,
        target_id=member.id,
        actor_id=actor.id,
        new_role="admin",
        new_status=None,
    )  # no raise


def test_guard_update_treats_a_suspended_admin_as_not_counting(conn) -> None:
    """One active admin plus one suspended admin: the active one is 'last'."""
    active_admin = create_user(conn, username="a", password_hash="h", role="admin")
    suspended = create_user(conn, username="b", password_hash="h", role="admin")
    update_user(conn, suspended.id, status="suspended")
    member = create_user(conn, username="c", password_hash="h", role="member")
    with pytest.raises(GuardError, match="last"):
        guard_update(
            conn,
            target_id=active_admin.id,
            actor_id=member.id,
            new_role=None,
            new_status="suspended",
        )


# ---------------------------------------------------------------------------
# MAJOR-2 — the atomic guarded mutators cannot empty the admin set
# ---------------------------------------------------------------------------


def test_apply_guarded_update_demotes_a_non_last_admin(conn) -> None:
    """apply_guarded_update applies a permitted demotion and returns the row."""
    actor = create_user(conn, username="a", password_hash="h", role="admin")
    other = create_user(conn, username="b", password_hash="h", role="admin")
    updated = apply_guarded_update(
        conn, target_id=other.id, actor_id=actor.id, role="member"
    )
    assert updated.role == "member"
    assert count_admins(conn) == 1


def test_apply_guarded_update_rejects_demoting_the_sequential_last_admin(
    conn,
) -> None:
    """A sequential last-admin demote is rejected and writes nothing.

    With one admin left, ``apply_guarded_update`` must raise ``GuardError`` and
    leave the row untouched — the guard read and the UPDATE are one atomic
    transaction, so a rejected guard rolls back cleanly.
    """
    only_admin = create_user(conn, username="a", password_hash="h", role="admin")
    member = create_user(conn, username="b", password_hash="h", role="member")
    with pytest.raises(GuardError, match="last"):
        apply_guarded_update(
            conn, target_id=only_admin.id, actor_id=member.id, role="member"
        )
    # Nothing was written — the admin is still an admin.
    still = get_by_id(conn, only_admin.id)
    assert still is not None and still.role == "admin"
    assert count_admins(conn) == 1


def test_apply_guarded_delete_rejects_deleting_the_last_admin(conn) -> None:
    """apply_guarded_delete rejects the last-admin delete and writes nothing."""
    only_admin = create_user(conn, username="a", password_hash="h", role="admin")
    member = create_user(conn, username="b", password_hash="h", role="member")
    with pytest.raises(GuardError, match="last"):
        apply_guarded_delete(conn, target_id=only_admin.id, actor_id=member.id)
    assert get_by_id(conn, only_admin.id) is not None
    assert count_admins(conn) == 1


def test_concurrent_guarded_demotes_cannot_reach_zero_admins(tmp_path) -> None:
    """Two concurrent guarded demotes of the two remaining admins keep one.

    This is the MAJOR-2 regression. The last-admin guard was a read-then-write
    TOCTOU: with two admins, two concurrent demotes both read ``count_admins``
    as 2, both passed ``> 1``, and both demoted — leaving **zero** admins, an
    unrecoverable lockout. ``apply_guarded_update`` now runs the guard read and
    the UPDATE inside one ``BEGIN IMMEDIATE`` transaction, so the second writer
    blocks on SQLite's write lock until the first commits and then sees one
    admin left — its guard rejects the demotion. Each thread uses its own
    connection, exactly the per-request model. Run with the old separate-
    statement guard this leaves zero admins and fails.
    """
    db_path = str(tmp_path / "app.db")
    setup_conn = connect(db_path)
    ensure_schema(setup_conn)
    admin_a = create_user(setup_conn, username="admin-a", password_hash="h", role="admin")
    admin_b = create_user(setup_conn, username="admin-b", password_hash="h", role="admin")
    # A non-admin actor, so the guard hit is "last admin", not "yourself".
    actor = create_user(setup_conn, username="actor", password_hash="h", role="member")
    setup_conn.close()

    outcomes: list[str] = []
    outcomes_lock = threading.Lock()
    start = threading.Barrier(2)

    def demote(target_id: int) -> None:
        conn = connect(db_path)
        try:
            start.wait()
            apply_guarded_update(
                conn, target_id=target_id, actor_id=actor.id, role="member"
            )
            with outcomes_lock:
                outcomes.append("demoted")
        except GuardError:
            with outcomes_lock:
                outcomes.append("rejected")
        finally:
            conn.close()

    threads = [
        threading.Thread(target=demote, args=(admin_a.id,)),
        threading.Thread(target=demote, args=(admin_b.id,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Exactly one demote succeeded and one was rejected by the guard.
    assert sorted(outcomes) == ["demoted", "rejected"], outcomes
    # The invariant held: at least one active admin always remains.
    verifier = connect(db_path)
    try:
        assert count_admins(verifier) == 1
    finally:
        verifier.close()
