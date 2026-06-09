"""Tests for the DB-backed session lifecycle in search.sessions.

Covers begin_session (creates a row keyed by the hashed token; returns the
raw token and an expiry in the future), resolve_session (returns a
CurrentUser for a live session; None for an unknown, expired, or
suspended-user session; prunes the expired row), end_session, and the
last_seen throttle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.sessions import create as create_session
from appdb.sessions import get_by_token_hash
from appdb.users import create as create_user
from appdb.users import update as update_user
from search.sessions import (
    CurrentUser,
    begin_session,
    end_session,
    hash_token,
    resolve_session,
    should_touch_last_seen,
)


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


@pytest.fixture()
def user(conn):
    """An active member user."""
    return create_user(conn, username="alice", password_hash="h", role="member")


def test_begin_session_returns_a_raw_token(conn, user) -> None:
    issued = begin_session(conn, user_id=user.id, ttl_seconds=3600)
    assert isinstance(issued.token, str)
    assert len(issued.token) >= 40


def test_begin_session_stores_only_the_hashed_token(conn, user) -> None:
    """The DB row is keyed by the SHA-256 of the token, not the raw token."""
    issued = begin_session(conn, user_id=user.id, ttl_seconds=3600)
    assert get_by_token_hash(conn, issued.token) is None
    assert get_by_token_hash(conn, hash_token(issued.token)) is not None


def test_begin_session_prunes_expired_sessions(conn, user) -> None:
    """A new login sweeps already-expired sessions so the table stays bounded.

    Regression guard for the sessions leak: prune_expired was dead code until
    begin_session was wired to call it. Without the sweep, a session whose
    owner never returns to present the cookie would live in app.db forever.
    """
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    create_session(
        conn,
        token_hash=hash_token("dead-token"),
        user_id=user.id,
        expires_at=past,
        user_agent=None,
        ip=None,
    )
    assert get_by_token_hash(conn, hash_token("dead-token")) is not None

    # A fresh login must prune the expired row...
    begin_session(conn, user_id=user.id, ttl_seconds=3600)

    # ...leaving only the new live session.
    assert get_by_token_hash(conn, hash_token("dead-token")) is None
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_begin_session_expiry_is_in_the_future(conn, user) -> None:
    issued = begin_session(conn, user_id=user.id, ttl_seconds=3600)
    expiry = datetime.fromisoformat(issued.expires_at)
    assert expiry > datetime.now(timezone.utc)


def test_begin_session_records_user_agent_and_ip(conn, user) -> None:
    issued = begin_session(
        conn,
        user_id=user.id,
        ttl_seconds=3600,
        user_agent="pytest-UA",
        ip="10.0.0.1",
    )
    row = get_by_token_hash(conn, hash_token(issued.token))
    assert row is not None
    assert row.user_agent == "pytest-UA"
    assert row.ip == "10.0.0.1"


def test_resolve_session_returns_the_current_user(conn, user) -> None:
    issued = begin_session(conn, user_id=user.id, ttl_seconds=3600)
    resolved = resolve_session(conn, issued.token)
    assert isinstance(resolved, CurrentUser)
    assert resolved.id == user.id
    assert resolved.username == "alice"
    assert resolved.role == "member"


def test_resolve_session_returns_none_for_an_unknown_token(conn) -> None:
    assert resolve_session(conn, "never-issued-token") is None


def test_resolve_session_returns_none_for_a_none_token(conn) -> None:
    assert resolve_session(conn, None) is None


def test_resolve_session_returns_none_for_an_expired_session(conn, user) -> None:
    issued = begin_session(conn, user_id=user.id, ttl_seconds=-10)
    assert resolve_session(conn, issued.token) is None


def test_resolve_session_prunes_the_expired_row(conn, user) -> None:
    """An expired session is deleted as a side effect of resolving it."""
    issued = begin_session(conn, user_id=user.id, ttl_seconds=-10)
    resolve_session(conn, issued.token)
    assert get_by_token_hash(conn, hash_token(issued.token)) is None


def test_resolve_session_returns_none_for_a_suspended_user(conn, user) -> None:
    issued = begin_session(conn, user_id=user.id, ttl_seconds=3600)
    update_user(conn, user.id, status="suspended")
    assert resolve_session(conn, issued.token) is None


def test_end_session_deletes_the_session(conn, user) -> None:
    issued = begin_session(conn, user_id=user.id, ttl_seconds=3600)
    end_session(conn, issued.token)
    assert resolve_session(conn, issued.token) is None


def test_end_session_is_silent_for_an_unknown_token(conn) -> None:
    end_session(conn, "no-such-token")  # must not raise


def test_should_touch_last_seen_true_when_stale(self_unused=None) -> None:
    """last_seen older than the throttle window asks for a write."""
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    assert should_touch_last_seen(stale) is True


def test_should_touch_last_seen_false_when_recent() -> None:
    """last_seen inside the throttle window does not ask for a write."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert should_touch_last_seen(recent) is False


def test_should_touch_last_seen_true_for_an_unparseable_value() -> None:
    """A malformed last_seen is treated as stale (write to repair it)."""
    assert should_touch_last_seen("not-a-timestamp") is True


def test_resolve_session_carries_display_name(conn) -> None:
    """resolve_session propagates the user's display_name onto CurrentUser."""
    user = create_user(
        conn,
        username="displaytest",
        password_hash="h",
        role="member",
        display_name="Vilmar Rosset",
    )
    issued = begin_session(conn, user_id=user.id, ttl_seconds=3600)
    resolved = resolve_session(conn, issued.token)
    assert resolved is not None
    assert resolved.display_name == "Vilmar Rosset"
