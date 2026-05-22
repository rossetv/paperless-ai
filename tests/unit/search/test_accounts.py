"""Tests for search.accounts — account operations and guards.

Covers the guard predicates the PATCH/DELETE handlers rely on:
- a user cannot delete or suspend or demote themselves;
- the last remaining admin cannot be deleted, suspended, or demoted;
- a non-self, non-last-admin change is permitted.
And the GuardError they raise.
"""

from __future__ import annotations

import pytest

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from appdb.users import update as update_user
from search.accounts import (
    GuardError,
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
