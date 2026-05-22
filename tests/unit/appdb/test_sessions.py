"""Tests for appdb.sessions — the Session dataclass and session queries.

Covers create (persists; populates timestamps), get_by_token_hash (hit and
miss; expired rows are still returned — expiry is the caller's check),
touch_last_seen, delete, delete_for_user (revokes every session of one user),
prune_expired (removes only past-expiry rows), and the ON DELETE CASCADE from
users to sessions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.sessions import (
    Session,
    create,
    delete,
    delete_for_user,
    get_by_token_hash,
    prune_expired,
    touch_last_seen,
)
from appdb.users import create as create_user


def _iso(offset_seconds: int) -> str:
    """An ISO-8601 UTC timestamp *offset_seconds* from now."""
    return (
        datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    ).isoformat()


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection with one user (id available via the
    ``user_id`` fixture)."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


@pytest.fixture()
def user_id(conn) -> int:
    """The id of a member user to own test sessions."""
    return create_user(
        conn, username="owner", password_hash="h", role="member"
    ).id


def test_create_returns_a_session(conn, user_id) -> None:
    session = create(
        conn,
        token_hash="hash-abc",
        user_id=user_id,
        expires_at=_iso(3600),
        user_agent="pytest",
        ip="127.0.0.1",
    )
    assert isinstance(session, Session)
    assert session.id > 0
    assert session.token_hash == "hash-abc"
    assert session.user_id == user_id
    assert session.user_agent == "pytest"
    assert session.ip == "127.0.0.1"


def test_create_populates_created_and_last_seen(conn, user_id) -> None:
    session = create(
        conn, token_hash="h", user_id=user_id, expires_at=_iso(3600)
    )
    assert session.created_at != ""
    assert session.last_seen_at != ""


def test_create_allows_omitted_user_agent_and_ip(conn, user_id) -> None:
    session = create(
        conn, token_hash="h", user_id=user_id, expires_at=_iso(3600)
    )
    assert session.user_agent is None
    assert session.ip is None


def test_get_by_token_hash_returns_the_session(conn, user_id) -> None:
    create(conn, token_hash="lookup-me", user_id=user_id, expires_at=_iso(3600))
    found = get_by_token_hash(conn, "lookup-me")
    assert found is not None
    assert found.token_hash == "lookup-me"


def test_get_by_token_hash_returns_none_when_absent(conn) -> None:
    assert get_by_token_hash(conn, "no-such-hash") is None


def test_get_by_token_hash_still_returns_an_expired_row(conn, user_id) -> None:
    """Expiry is the caller's check; the lookup itself does not filter it.

    get_current_user must compare expires_at against the clock — the row is
    returned so that comparison can happen (and the row can be pruned)."""
    create(conn, token_hash="expired", user_id=user_id, expires_at=_iso(-10))
    assert get_by_token_hash(conn, "expired") is not None


def test_touch_last_seen_advances_the_timestamp(conn, user_id) -> None:
    create(conn, token_hash="h", user_id=user_id, expires_at=_iso(3600))
    original = get_by_token_hash(conn, "h").last_seen_at
    touch_last_seen(conn, "h", seen_at="2099-01-01T00:00:00+00:00")
    assert get_by_token_hash(conn, "h").last_seen_at == "2099-01-01T00:00:00+00:00"
    assert get_by_token_hash(conn, "h").last_seen_at != original


def test_delete_removes_the_session(conn, user_id) -> None:
    create(conn, token_hash="bye", user_id=user_id, expires_at=_iso(3600))
    delete(conn, "bye")
    assert get_by_token_hash(conn, "bye") is None


def test_delete_is_silent_for_an_unknown_token(conn) -> None:
    delete(conn, "never-existed")  # must not raise


def test_delete_for_user_removes_every_session_of_that_user(conn, user_id) -> None:
    create(conn, token_hash="s1", user_id=user_id, expires_at=_iso(3600))
    create(conn, token_hash="s2", user_id=user_id, expires_at=_iso(3600))
    delete_for_user(conn, user_id)
    assert get_by_token_hash(conn, "s1") is None
    assert get_by_token_hash(conn, "s2") is None


def test_delete_for_user_leaves_other_users_sessions(conn, user_id) -> None:
    other = create_user(
        conn, username="other", password_hash="h", role="member"
    ).id
    create(conn, token_hash="mine", user_id=user_id, expires_at=_iso(3600))
    create(conn, token_hash="theirs", user_id=other, expires_at=_iso(3600))
    delete_for_user(conn, user_id)
    assert get_by_token_hash(conn, "theirs") is not None


def test_prune_expired_removes_only_past_sessions(conn, user_id) -> None:
    create(conn, token_hash="live", user_id=user_id, expires_at=_iso(3600))
    create(conn, token_hash="dead", user_id=user_id, expires_at=_iso(-3600))
    removed = prune_expired(conn, now_iso=datetime.now(timezone.utc).isoformat())
    assert removed == 1
    assert get_by_token_hash(conn, "live") is not None
    assert get_by_token_hash(conn, "dead") is None


def test_deleting_a_user_cascades_to_their_sessions(conn, user_id) -> None:
    """ON DELETE CASCADE: removing the user removes their sessions."""
    from appdb.users import delete as delete_user

    create(conn, token_hash="cascade", user_id=user_id, expires_at=_iso(3600))
    delete_user(conn, user_id)
    assert get_by_token_hash(conn, "cascade") is None
