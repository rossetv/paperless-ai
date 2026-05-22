"""Tests for search.auth — the post-Wave-3 authentication primitives.

Covers extract_bearer (the header parser), api_key_caller (a live key
resolves to its owner's CurrentUser; an unknown/revoked key and a None
bearer resolve to None), and authorise_role (the RBAC ranking).
"""

from __future__ import annotations

import pytest

from appdb.api_keys import create as create_key
from appdb.api_keys import revoke as revoke_key
from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from search.api_keys import generate_raw_key, hash_key, key_display_prefix
from search.auth import api_key_caller, authorise_role, extract_bearer
from search.sessions import CurrentUser


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db with one admin owner (id 1)."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    create_user(c, username="owner", password_hash="h", role="admin")
    yield c
    c.close()


def _mint(conn, *, scopes="api") -> str:
    raw = generate_raw_key()
    create_key(
        conn,
        key_hash=hash_key(raw),
        key_prefix=key_display_prefix(raw),
        name="k",
        owner_user_id=1,
        scopes=scopes,
    )
    return raw


def test_extract_bearer_returns_the_token() -> None:
    assert extract_bearer("Bearer abc123") == "abc123"


def test_extract_bearer_returns_none_for_no_header() -> None:
    assert extract_bearer(None) is None


def test_extract_bearer_returns_none_for_a_non_bearer_scheme() -> None:
    assert extract_bearer("Basic abc123") is None


def test_extract_bearer_is_case_sensitive_on_the_scheme() -> None:
    assert extract_bearer("bearer abc123") is None


def test_api_key_caller_resolves_a_live_key(conn) -> None:
    raw = _mint(conn)
    caller = api_key_caller(conn, raw)
    assert isinstance(caller, CurrentUser)
    assert caller.id == 1
    assert caller.username == "owner"
    assert caller.role == "admin"


def test_api_key_caller_returns_none_for_a_none_bearer(conn) -> None:
    assert api_key_caller(conn, None) is None


def test_api_key_caller_returns_none_for_an_unknown_key(conn) -> None:
    assert api_key_caller(conn, "sk-pls-nope") is None


def test_api_key_caller_returns_none_for_a_revoked_key(conn) -> None:
    raw = _mint(conn)
    key_hash = hash_key(raw)
    from appdb.api_keys import get_by_hash

    record = get_by_hash(conn, key_hash)
    assert record is not None
    revoke_key(conn, record.id, revoked_at="2026-05-22T00:00:00+00:00")
    assert api_key_caller(conn, raw) is None


def test_authorise_role_allows_an_equal_role() -> None:
    assert authorise_role("member", "member") is True


def test_authorise_role_allows_a_higher_role() -> None:
    assert authorise_role("admin", "member") is True


def test_authorise_role_denies_a_lower_role() -> None:
    assert authorise_role("readonly", "member") is False


def test_authorise_role_denies_an_unknown_caller_role() -> None:
    assert authorise_role("wizard", "readonly") is False


def test_authorise_role_denies_an_unknown_requirement() -> None:
    assert authorise_role("admin", "godmode") is False
