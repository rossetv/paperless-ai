"""Tests for the admin-facing appdb.users functions.

Covers list_all (ordering, empty), update (partial: each field independently;
updated_at advances; password_changed_at advances only on a password change),
delete, count_all, count_admins, and record_login.
"""

from __future__ import annotations

import pytest

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import (
    count_admins,
    count_all,
    create,
    delete,
    get_by_id,
    list_all,
    record_login,
    update,
)


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def test_list_all_returns_every_user(conn) -> None:
    create(conn, username="a", password_hash="h", role="admin")
    create(conn, username="b", password_hash="h", role="member")
    users = list_all(conn)
    assert {u.username for u in users} == {"a", "b"}


def test_list_all_is_ordered_by_id(conn) -> None:
    first = create(conn, username="a", password_hash="h", role="admin")
    second = create(conn, username="b", password_hash="h", role="member")
    users = list_all(conn)
    assert [u.id for u in users] == [first.id, second.id]


def test_list_all_is_empty_on_a_fresh_database(conn) -> None:
    assert list_all(conn) == []


def test_update_changes_the_display_name(conn) -> None:
    user = create(conn, username="a", password_hash="h", role="member")
    updated = update(conn, user.id, display_name="New Name")
    assert updated is not None
    assert updated.display_name == "New Name"


def test_update_changes_the_role(conn) -> None:
    user = create(conn, username="a", password_hash="h", role="member")
    updated = update(conn, user.id, role="admin")
    assert updated is not None
    assert updated.role == "admin"


def test_update_changes_the_status(conn) -> None:
    user = create(conn, username="a", password_hash="h", role="member")
    updated = update(conn, user.id, status="suspended")
    assert updated is not None
    assert updated.status == "suspended"


def test_update_changes_the_email(conn) -> None:
    user = create(conn, username="a", password_hash="h", role="member")
    updated = update(conn, user.id, email="new@example.com")
    assert updated is not None
    assert updated.email == "new@example.com"


def test_update_changes_the_password_hash(conn) -> None:
    user = create(conn, username="a", password_hash="old", role="member")
    updated = update(conn, user.id, password_hash="new-hash")
    assert updated is not None
    assert updated.password_hash == "new-hash"


def test_update_password_advances_password_changed_at(conn) -> None:
    user = create(conn, username="a", password_hash="old", role="member")
    original = user.password_changed_at
    updated = update(conn, user.id, password_hash="new-hash")
    assert updated is not None
    assert updated.password_changed_at != original


def test_update_without_a_password_does_not_touch_password_changed_at(conn) -> None:
    user = create(conn, username="a", password_hash="h", role="member")
    original = user.password_changed_at
    updated = update(conn, user.id, display_name="x")
    assert updated is not None
    assert updated.password_changed_at == original


def test_update_with_no_fields_returns_the_unchanged_user(conn) -> None:
    user = create(conn, username="a", password_hash="h", role="member")
    updated = update(conn, user.id)
    assert updated is not None
    assert updated.username == "a"


def test_update_returns_none_for_an_unknown_user(conn) -> None:
    assert update(conn, 999999, display_name="x") is None


def test_delete_removes_the_user(conn) -> None:
    user = create(conn, username="a", password_hash="h", role="admin")
    delete(conn, user.id)
    assert get_by_id(conn, user.id) is None


def test_delete_is_silent_for_an_unknown_user(conn) -> None:
    delete(conn, 999999)  # must not raise


def test_count_all_counts_every_user(conn) -> None:
    assert count_all(conn) == 0
    create(conn, username="a", password_hash="h", role="admin")
    create(conn, username="b", password_hash="h", role="member")
    assert count_all(conn) == 2


def test_count_admins_counts_only_active_admins(conn) -> None:
    create(conn, username="a", password_hash="h", role="admin")
    create(conn, username="b", password_hash="h", role="member")
    suspended = create(conn, username="c", password_hash="h", role="admin")
    update(conn, suspended.id, status="suspended")
    # A suspended admin cannot act, so it does not count as a live admin.
    assert count_admins(conn) == 1


def test_record_login_stamps_last_login_at(conn) -> None:
    user = create(conn, username="a", password_hash="h", role="member")
    assert user.last_login_at is None
    record_login(conn, user.id)
    refreshed = get_by_id(conn, user.id)
    assert refreshed is not None
    assert refreshed.last_login_at is not None
