"""Tests for appdb.recent_searches, the per-user recent-search history."""

from __future__ import annotations

import sqlite3

import pytest

from appdb.connection import connect
from appdb.recent_searches import (
    MAX_PER_USER,
    RecentSearch,
    list_for_user,
    record,
)
from appdb.schema import ensure_schema
from appdb.users import create as create_user


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection with two users seeded."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    create_user(c, username="alice", password_hash="h", role="member")
    create_user(c, username="bob", password_hash="h", role="member")
    yield c
    c.close()


def _user_id(conn: sqlite3.Connection, username: str) -> int:
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    return int(row["id"])


def test_record_returns_a_recent_search(conn) -> None:
    uid = _user_id(conn, "alice")
    result = record(conn, user_id=uid, query="gas bill")
    assert isinstance(result, RecentSearch)
    assert result.user_id == uid
    assert result.query == "gas bill"
    assert result.id > 0
    assert result.created_at  # a non-empty ISO timestamp


def test_list_for_user_returns_the_recorded_query(conn) -> None:
    uid = _user_id(conn, "alice")
    record(conn, user_id=uid, query="gas bill")
    rows = list_for_user(conn, uid)
    assert [r.query for r in rows] == ["gas bill"]


def test_list_for_user_is_newest_first(conn) -> None:
    uid = _user_id(conn, "alice")
    record(conn, user_id=uid, query="first")
    record(conn, user_id=uid, query="second")
    record(conn, user_id=uid, query="third")
    rows = list_for_user(conn, uid)
    assert [r.query for r in rows] == ["third", "second", "first"]


def test_recording_an_identical_query_deduplicates(conn) -> None:
    """Re-running a query moves it to the top instead of adding a duplicate."""
    uid = _user_id(conn, "alice")
    record(conn, user_id=uid, query="gas bill")
    record(conn, user_id=uid, query="water bill")
    record(conn, user_id=uid, query="gas bill")  # repeat
    rows = list_for_user(conn, uid)
    assert [r.query for r in rows] == ["gas bill", "water bill"]


def test_history_is_capped_at_max_per_user(conn) -> None:
    uid = _user_id(conn, "alice")
    for i in range(MAX_PER_USER + 5):
        record(conn, user_id=uid, query=f"query-{i}")
    rows = list_for_user(conn, uid, limit=1000)
    assert len(rows) == MAX_PER_USER
    queries = {r.query for r in rows}
    assert "query-0" not in queries
    assert f"query-{MAX_PER_USER + 4}" in queries


def test_list_for_user_isolates_users(conn) -> None:
    alice = _user_id(conn, "alice")
    bob = _user_id(conn, "bob")
    record(conn, user_id=alice, query="alice query")
    record(conn, user_id=bob, query="bob query")
    assert [r.query for r in list_for_user(conn, alice)] == ["alice query"]
    assert [r.query for r in list_for_user(conn, bob)] == ["bob query"]


def test_list_for_user_honours_an_explicit_limit(conn) -> None:
    uid = _user_id(conn, "alice")
    for i in range(10):
        record(conn, user_id=uid, query=f"q-{i}")
    rows = list_for_user(conn, uid, limit=3)
    assert [r.query for r in rows] == ["q-9", "q-8", "q-7"]


def test_list_for_user_empty_history_is_empty_list(conn) -> None:
    uid = _user_id(conn, "alice")
    assert list_for_user(conn, uid) == []


def test_record_is_atomic_when_the_trim_fails(conn, monkeypatch) -> None:
    """The delete, insert and trim share one transaction, so a trim failure
    leaves the prior history untouched."""
    import appdb.recent_searches as recent_searches

    uid = _user_id(conn, "alice")
    record(conn, user_id=uid, query="original")

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated trim failure")

    monkeypatch.setattr(recent_searches, "_trim_to_cap", _boom)

    with pytest.raises(RuntimeError, match="simulated trim failure"):
        record(conn, user_id=uid, query="should be rolled back")

    queries = [r.query for r in list_for_user(conn, uid)]
    assert queries == ["original"]
