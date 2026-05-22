"""Tests for appdb.api_keys — the ApiKey dataclass and key query functions.

Covers create (returns a populated ApiKey; persists the row; defaults
optional columns) and get_by_hash (hit, miss). The list / revoke / delete /
touch functions are exercised in test_api_keys_admin.py.
"""

from __future__ import annotations

import pytest

from appdb.api_keys import ApiKey, create, get_by_hash
from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection with one owner user (id 1)."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    create_user(c, username="owner", password_hash="h", role="member")
    yield c
    c.close()


def test_create_returns_an_api_key_with_an_id(conn) -> None:
    key = create(
        conn,
        key_hash="hash-1",
        key_prefix="sk-pls-abcd",
        name="CI token",
        owner_user_id=1,
        scopes="api,mcp",
    )
    assert isinstance(key, ApiKey)
    assert key.id > 0
    assert key.key_hash == "hash-1"
    assert key.key_prefix == "sk-pls-abcd"
    assert key.name == "CI token"
    assert key.owner_user_id == 1
    assert key.scopes == "api,mcp"


def test_create_sets_created_at_and_zero_request_count(conn) -> None:
    key = create(
        conn,
        key_hash="hash-2",
        key_prefix="sk-pls-wxyz",
        name="k",
        owner_user_id=1,
        scopes="api",
    )
    assert key.created_at != ""
    assert key.request_count == 0


def test_create_defaults_optional_timestamps_to_none(conn) -> None:
    key = create(
        conn,
        key_hash="hash-3",
        key_prefix="sk-pls-0000",
        name="k",
        owner_user_id=1,
        scopes="api",
    )
    assert key.expires_at is None
    assert key.last_used_at is None
    assert key.revoked_at is None


def test_create_accepts_an_explicit_expiry(conn) -> None:
    key = create(
        conn,
        key_hash="hash-4",
        key_prefix="sk-pls-1111",
        name="k",
        owner_user_id=1,
        scopes="api",
        expires_at="2027-01-01T00:00:00+00:00",
    )
    assert key.expires_at == "2027-01-01T00:00:00+00:00"


def test_create_persists_the_row(conn) -> None:
    create(
        conn,
        key_hash="hash-5",
        key_prefix="sk-pls-2222",
        name="persisted",
        owner_user_id=1,
        scopes="mcp",
    )
    fetched = get_by_hash(conn, "hash-5")
    assert fetched is not None
    assert fetched.name == "persisted"
    assert fetched.scopes == "mcp"


def test_create_rejects_a_duplicate_key_hash(conn) -> None:
    """The key_hash UNIQUE constraint surfaces as DuplicateKeyHashError."""
    from appdb.api_keys import DuplicateKeyHashError

    create(
        conn,
        key_hash="same",
        key_prefix="sk-pls-3333",
        name="one",
        owner_user_id=1,
        scopes="api",
    )
    with pytest.raises(DuplicateKeyHashError):
        create(
            conn,
            key_hash="same",
            key_prefix="sk-pls-4444",
            name="two",
            owner_user_id=1,
            scopes="api",
        )


def test_get_by_hash_returns_none_when_absent(conn) -> None:
    assert get_by_hash(conn, "no-such-hash") is None


def test_get_by_hash_returns_the_key(conn) -> None:
    created = create(
        conn,
        key_hash="hash-6",
        key_prefix="sk-pls-5555",
        name="k",
        owner_user_id=1,
        scopes="api",
    )
    fetched = get_by_hash(conn, "hash-6")
    assert fetched is not None
    assert fetched.id == created.id
