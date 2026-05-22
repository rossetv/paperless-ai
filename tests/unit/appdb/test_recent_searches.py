"""Tests for appdb.recent_searches — per-user recent-search history.

Covers the contract: record inserts a row; list_for_user returns a user's
searches newest-first; recording an identical query de-duplicates (the old
row is removed, the query moves to the top); the per-user history is capped
at MAX_PER_USER, oldest dropped; one user never sees another's searches;
list_for_user honours an explicit limit; an empty history returns [].
"""

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
    """Return the id of the seeded user named *username*."""
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    return int(row["id"])


def test_record_returns_a_recent_search(conn) -> None:
    """record returns the inserted row as a RecentSearch."""
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
    """Searches come back in reverse-chronological order."""
    uid = _user_id(conn, "alice")
    record(conn, user_id=uid, query="first")
    record(conn, user_id=uid, query="second")
    record(conn, user_id=uid, query="third")
    rows = list_for_user(conn, uid)
    assert [r.query for r in rows] == ["third", "second", "first"]


def test_recording_an_identical_query_deduplicates(conn) -> None:
    """Re-running an identical query moves it to the top, no duplicate row."""
    uid = _user_id(conn, "alice")
    record(conn, user_id=uid, query="gas bill")
    record(conn, user_id=uid, query="water bill")
    record(conn, user_id=uid, query="gas bill")  # repeat
    rows = list_for_user(conn, uid)
    assert [r.query for r in rows] == ["gas bill", "water bill"]


def test_history_is_capped_at_max_per_user(conn) -> None:
    """Beyond MAX_PER_USER rows, the oldest searches are dropped."""
    uid = _user_id(conn, "alice")
    for i in range(MAX_PER_USER + 5):
        record(conn, user_id=uid, query=f"query-{i}")
    rows = list_for_user(conn, uid, limit=1000)
    assert len(rows) == MAX_PER_USER
    # The five oldest (query-0 .. query-4) were evicted.
    queries = {r.query for r in rows}
    assert "query-0" not in queries
    assert f"query-{MAX_PER_USER + 4}" in queries


def test_list_for_user_isolates_users(conn) -> None:
    """One user's list never contains another user's searches."""
    alice = _user_id(conn, "alice")
    bob = _user_id(conn, "bob")
    record(conn, user_id=alice, query="alice query")
    record(conn, user_id=bob, query="bob query")
    assert [r.query for r in list_for_user(conn, alice)] == ["alice query"]
    assert [r.query for r in list_for_user(conn, bob)] == ["bob query"]


def test_list_for_user_honours_an_explicit_limit(conn) -> None:
    """A smaller limit returns only that many newest rows."""
    uid = _user_id(conn, "alice")
    for i in range(10):
        record(conn, user_id=uid, query=f"q-{i}")
    rows = list_for_user(conn, uid, limit=3)
    assert [r.query for r in rows] == ["q-9", "q-8", "q-7"]


def test_list_for_user_empty_history_is_empty_list(conn) -> None:
    """A user who has never searched gets an empty list."""
    uid = _user_id(conn, "alice")
    assert list_for_user(conn, uid) == []
