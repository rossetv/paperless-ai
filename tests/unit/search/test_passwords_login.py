"""Tests for search.passwords_login — credential authentication.

Covers: authenticate returns the User for a correct username/password;
None for a wrong password; None for an unknown username; it returns a
suspended user too (status is the login handler's concern, not this
function's) so the handler can issue a distinct 403.
"""

from __future__ import annotations

import pytest

from appdb.connection import connect
from appdb.passwords import hash_password
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from appdb.users import update as update_user
from search.passwords_login import authenticate


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection with one member user 'alice'."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    create_user(
        c,
        username="alice",
        password_hash=hash_password("correct-password"),
        role="member",
    )
    yield c
    c.close()


def test_authenticate_returns_the_user_for_correct_credentials(conn) -> None:
    user = authenticate(conn, "alice", "correct-password")
    assert user is not None
    assert user.username == "alice"


def test_authenticate_returns_none_for_a_wrong_password(conn) -> None:
    assert authenticate(conn, "alice", "wrong-password") is None


def test_authenticate_returns_none_for_an_unknown_username(conn) -> None:
    assert authenticate(conn, "nobody", "any-password") is None


def test_authenticate_returns_a_suspended_user(conn) -> None:
    """Status is the handler's concern — authenticate still returns the row."""
    alice = authenticate(conn, "alice", "correct-password")
    assert alice is not None
    update_user(conn, alice.id, status="suspended")
    result = authenticate(conn, "alice", "correct-password")
    assert result is not None
    assert result.status == "suspended"
