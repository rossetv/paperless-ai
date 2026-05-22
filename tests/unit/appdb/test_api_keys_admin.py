"""Tests for the admin/list/lifecycle appdb.api_keys functions.

Covers get_by_id (hit, miss), list_all (ordering, empty), list_for_user
(filtering by owner), revoke (sets revoked_at, idempotent), delete, the
throttled touch (advances last_used_at and request_count), and update
(partial edits, clearing the expiry, no-op, unknown id).
"""

from __future__ import annotations

import pytest

from appdb.api_keys import (
    create,
    delete,
    get_by_id,
    list_all,
    list_for_user,
    revoke,
    touch,
    update,
)
from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db with two owner users (ids 1 and 2)."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    create_user(c, username="alice", password_hash="h", role="member")
    create_user(c, username="bob", password_hash="h", role="member")
    yield c
    c.close()


def _make(conn, *, key_hash, owner_user_id=1, name="k", scopes="api"):
    return create(
        conn,
        key_hash=key_hash,
        key_prefix="sk-pls-" + key_hash[:4],
        name=name,
        owner_user_id=owner_user_id,
        scopes=scopes,
    )


def test_get_by_id_returns_the_key(conn) -> None:
    created = _make(conn, key_hash="h1")
    fetched = get_by_id(conn, created.id)
    assert fetched is not None
    assert fetched.id == created.id


def test_get_by_id_returns_none_when_absent(conn) -> None:
    assert get_by_id(conn, 999999) is None


def test_list_all_returns_every_key_ordered_by_id(conn) -> None:
    a = _make(conn, key_hash="h1")
    b = _make(conn, key_hash="h2")
    ids = [k.id for k in list_all(conn)]
    assert ids == [a.id, b.id]


def test_list_all_is_empty_when_no_keys(conn) -> None:
    assert list_all(conn) == []


def test_list_for_user_filters_by_owner(conn) -> None:
    _make(conn, key_hash="h1", owner_user_id=1)
    _make(conn, key_hash="h2", owner_user_id=2)
    _make(conn, key_hash="h3", owner_user_id=1)
    alice_keys = list_for_user(conn, 1)
    assert {k.key_hash for k in alice_keys} == {"h1", "h3"}
    assert all(k.owner_user_id == 1 for k in alice_keys)


def test_list_for_user_is_empty_for_an_owner_with_no_keys(conn) -> None:
    _make(conn, key_hash="h1", owner_user_id=1)
    assert list_for_user(conn, 2) == []


def test_revoke_sets_revoked_at(conn) -> None:
    created = _make(conn, key_hash="h1")
    revoke(conn, created.id, revoked_at="2026-05-22T00:00:00+00:00")
    fetched = get_by_id(conn, created.id)
    assert fetched is not None
    assert fetched.revoked_at == "2026-05-22T00:00:00+00:00"


def test_revoke_is_idempotent(conn) -> None:
    """Revoking an already-revoked key keeps the original timestamp intact
    only changing it on the second call is acceptable; the function must not
    raise and the key stays revoked."""
    created = _make(conn, key_hash="h1")
    revoke(conn, created.id, revoked_at="2026-05-22T00:00:00+00:00")
    revoke(conn, created.id, revoked_at="2026-05-23T00:00:00+00:00")
    fetched = get_by_id(conn, created.id)
    assert fetched is not None
    assert fetched.revoked_at is not None


def test_revoke_of_an_unknown_id_is_a_no_op(conn) -> None:
    revoke(conn, 999999, revoked_at="2026-05-22T00:00:00+00:00")  # no raise


def test_delete_removes_the_row(conn) -> None:
    created = _make(conn, key_hash="h1")
    delete(conn, created.id)
    assert get_by_id(conn, created.id) is None


def test_delete_of_an_unknown_id_is_a_no_op(conn) -> None:
    delete(conn, 999999)  # no raise


def test_touch_advances_last_used_at_and_request_count(conn) -> None:
    created = _make(conn, key_hash="h1")
    touch(conn, created.id, used_at="2026-05-22T10:00:00+00:00")
    fetched = get_by_id(conn, created.id)
    assert fetched is not None
    assert fetched.last_used_at == "2026-05-22T10:00:00+00:00"
    assert fetched.request_count == 1


def test_touch_increments_request_count_each_call(conn) -> None:
    created = _make(conn, key_hash="h1")
    touch(conn, created.id, used_at="2026-05-22T10:00:00+00:00")
    touch(conn, created.id, used_at="2026-05-22T11:00:00+00:00")
    touch(conn, created.id, used_at="2026-05-22T12:00:00+00:00")
    fetched = get_by_id(conn, created.id)
    assert fetched is not None
    assert fetched.request_count == 3
    assert fetched.last_used_at == "2026-05-22T12:00:00+00:00"


def test_touch_of_an_unknown_id_is_a_no_op(conn) -> None:
    touch(conn, 999999, used_at="2026-05-22T10:00:00+00:00")  # no raise


def test_update_changes_the_supplied_fields(conn) -> None:
    created = _make(conn, key_hash="h1", name="old", scopes="api")
    updated = update(
        conn,
        created.id,
        name="renamed",
        scopes="api,mcp",
        expires_at="2027-01-01T00:00:00+00:00",
    )
    assert updated is not None
    assert updated.name == "renamed"
    assert updated.scopes == "api,mcp"
    assert updated.expires_at == "2027-01-01T00:00:00+00:00"


def test_update_leaves_omitted_fields_untouched(conn) -> None:
    """A field not passed keeps its stored value — only `name` changes here."""
    created = _make(conn, key_hash="h1", name="old", scopes="api")
    updated = update(conn, created.id, name="renamed")
    assert updated is not None
    assert updated.name == "renamed"
    assert updated.scopes == "api"
    assert updated.expires_at is None


def test_update_can_clear_the_expiry_with_none(conn) -> None:
    """Passing expires_at=None clears an expiry — distinct from omitting it."""
    created = create(
        conn,
        key_hash="h1",
        key_prefix="sk-pls-h1",
        name="k",
        owner_user_id=1,
        scopes="api",
        expires_at="2027-01-01T00:00:00+00:00",
    )
    updated = update(conn, created.id, expires_at=None)
    assert updated is not None
    assert updated.expires_at is None


def test_update_with_no_fields_is_a_no_op_returning_the_row(conn) -> None:
    created = _make(conn, key_hash="h1", name="unchanged")
    updated = update(conn, created.id)
    assert updated is not None
    assert updated.name == "unchanged"


def test_update_of_an_unknown_id_returns_none(conn) -> None:
    assert update(conn, 999999, name="x") is None
