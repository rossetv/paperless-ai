"""Tests for search.api_keys.resolve_api_key — the bearer-auth lookup.

Covers: a live key resolves to a ResolvedKey carrying the owner, the owner's
role and the parsed scopes; an unknown key, a revoked key, an expired key
and a suspended owner's key all resolve to None (fail closed); a None
bearer resolves to None; an unexpired explicit expiry resolves fine.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from appdb.api_keys import create as create_key
from appdb.api_keys import revoke as revoke_key
from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from appdb.users import update as update_user
from search.api_keys import (
    ResolvedKey,
    generate_raw_key,
    hash_key,
    key_display_prefix,
    resolve_api_key,
)


def _iso(delta_seconds: int) -> str:
    """An ISO-8601 UTC timestamp offset from now by delta_seconds."""
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db with one active member owner (id 1)."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    create_user(c, username="owner", password_hash="h", role="member")
    yield c
    c.close()


def _mint(conn, *, scopes="api", owner_user_id=1, expires_at=None):
    """Create a key the proper way and return the raw key string."""
    raw = generate_raw_key()
    create_key(
        conn,
        key_hash=hash_key(raw),
        key_prefix=key_display_prefix(raw),
        name="k",
        owner_user_id=owner_user_id,
        scopes=scopes,
        expires_at=expires_at,
    )
    return raw


def test_resolve_a_live_key_returns_a_resolved_key(conn) -> None:
    raw = _mint(conn, scopes="api,mcp")
    resolved = resolve_api_key(conn, raw)
    assert isinstance(resolved, ResolvedKey)
    assert resolved.owner_user_id == 1
    assert resolved.owner_username == "owner"
    assert resolved.owner_role == "member"
    assert resolved.scopes == frozenset({"api", "mcp"})


def test_resolve_carries_the_api_key_id(conn) -> None:
    raw = _mint(conn)
    resolved = resolve_api_key(conn, raw)
    assert resolved is not None
    assert resolved.api_key_id > 0


def test_resolve_an_unknown_key_returns_none(conn) -> None:
    assert resolve_api_key(conn, "sk-pls-not-a-real-key") is None


def test_resolve_a_none_bearer_returns_none(conn) -> None:
    assert resolve_api_key(conn, None) is None


def test_resolve_a_revoked_key_returns_none(conn) -> None:
    raw = _mint(conn)
    resolved = resolve_api_key(conn, raw)
    assert resolved is not None
    revoke_key(conn, resolved.api_key_id, revoked_at=_iso(0))
    assert resolve_api_key(conn, raw) is None


def test_resolve_an_expired_key_returns_none(conn) -> None:
    raw = _mint(conn, expires_at=_iso(-3600))  # expired an hour ago
    assert resolve_api_key(conn, raw) is None


def test_resolve_an_unexpired_key_resolves(conn) -> None:
    raw = _mint(conn, expires_at=_iso(3600))  # expires in an hour
    assert resolve_api_key(conn, raw) is not None


def test_resolve_a_naive_future_expiry_does_not_raise_and_is_live(conn) -> None:
    """A tz-naive future expiry is coerced to UTC, not crashed on (H1).

    A key minted (or hand-edited) with a naive ISO timestamp must never raise
    ``TypeError`` out of the fail-closed lookup; a future naive expiry reads as
    a live key.
    """
    raw = _mint(conn, expires_at="2099-01-01T00:00:00")
    assert resolve_api_key(conn, raw) is not None


def test_resolve_a_naive_past_expiry_returns_none_without_raising(conn) -> None:
    """A tz-naive *past* expiry resolves to None (expired), never raising (H1)."""
    raw = _mint(conn, expires_at="2000-01-01T00:00:00")
    assert resolve_api_key(conn, raw) is None


def test_resolve_a_garbage_expiry_fails_closed(conn) -> None:
    """An unparseable stored expiry is treated as expired, not a 500 (H1)."""
    raw = _mint(conn, expires_at="not-a-date")
    assert resolve_api_key(conn, raw) is None


def test_resolve_a_suspended_owners_key_returns_none(conn) -> None:
    raw = _mint(conn)
    update_user(conn, 1, status="suspended")
    assert resolve_api_key(conn, raw) is None


def test_resolve_reflects_a_changed_owner_role(conn) -> None:
    """The owner's *current* role bounds the key — not the role at mint."""
    raw = _mint(conn)
    update_user(conn, 1, role="admin")
    resolved = resolve_api_key(conn, raw)
    assert resolved is not None
    assert resolved.owner_role == "admin"


def test_resolved_key_carries_owner_display_name(tmp_path) -> None:
    """resolve_api_key propagates the owner's display_name onto ResolvedKey."""
    from appdb.connection import connect
    from appdb.schema import ensure_schema

    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    create_user(
        c,
        username="display-owner",
        password_hash="h",
        role="member",
        display_name="Vilmar Rosset",
    )
    raw = _mint(c, owner_user_id=1)
    resolved = resolve_api_key(c, raw)
    assert resolved is not None
    assert resolved.owner_display_name == "Vilmar Rosset"
    c.close()
