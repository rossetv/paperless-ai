"""Tests for appdb.users — the User dataclass and user query functions.

Covers create (returns a populated User; persists the row), get_by_username
and get_by_id (hit and miss), the username UNIQUE constraint surfacing as a
typed error, and timestamp population. Also covers create_initial_admin:
inserts on an empty table, returns None on a non-empty table. The
list/update/delete/count functions are exercised in test_users_admin.py.
"""

from __future__ import annotations

import sqlite3

import pytest

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import (
    User,
    UsernameTakenError,
    create,
    create_initial_admin,
    get_by_id,
    get_by_username,
    update,
)


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def test_create_returns_a_user_with_an_id(conn) -> None:
    user = create(
        conn,
        username="alice",
        password_hash="hash-1",
        display_name="Alice",
        email="alice@example.com",
        role="admin",
    )
    assert isinstance(user, User)
    assert user.id > 0
    assert user.username == "alice"
    assert user.display_name == "Alice"
    assert user.email == "alice@example.com"
    assert user.role == "admin"
    assert user.status == "active"


def test_create_populates_created_and_updated_timestamps(conn) -> None:
    user = create(conn, username="bob", password_hash="h", role="member")
    assert user.created_at != ""
    assert user.updated_at != ""
    assert user.last_login_at is None


def test_create_persists_the_row(conn) -> None:
    create(conn, username="carol", password_hash="h", role="readonly")
    fetched = get_by_username(conn, "carol")
    assert fetched is not None
    assert fetched.username == "carol"
    assert fetched.role == "readonly"


def test_create_with_optional_fields_omitted(conn) -> None:
    user = create(conn, username="dave", password_hash="h", role="member")
    assert user.display_name is None
    assert user.email is None


def test_create_rejects_a_duplicate_username(conn) -> None:
    create(conn, username="eve", password_hash="h", role="member")
    with pytest.raises(UsernameTakenError):
        create(conn, username="eve", password_hash="h2", role="admin")


def test_update_rolls_back_and_leaves_no_open_transaction_on_failure(conn) -> None:
    """A mid-transaction failure rolls back cleanly via ``with conn:`` (§9.6).

    Regression for the bare-``conn.commit()`` write path: when the UPDATE
    statement raises (here, an invalid ``role`` rejected by the table's CHECK
    constraint), the ``with conn:`` context manager must roll back and leave the
    connection with **no open transaction**. The old code reached ``conn.commit()``
    only on the happy path, so a raised statement left the transaction dangling —
    poisoning the very next writer on this connection with
    "cannot start a transaction within a transaction". This test fails against
    the bare-commit version and passes once the write is wrapped.
    """
    created = create(conn, username="trent", password_hash="h", role="member")

    # An invalid role is rejected by the users.role CHECK constraint, so the
    # UPDATE raises *inside* the with-block. The Role type is a Literal — a type
    # ignore lets the test pass a value the DB layer (not mypy) rejects.
    with pytest.raises(sqlite3.IntegrityError):
        update(conn, created.id, role="superadmin")  # type: ignore[arg-type]

    # The rollback ran: the connection is clean, not stuck mid-transaction.
    assert conn.in_transaction is False

    # The next write on the same connection succeeds — proof the transaction was
    # not left open — and the failed update left the row's prior state intact.
    refreshed = update(conn, created.id, display_name="Trent")
    assert refreshed is not None
    assert refreshed.role == "member"
    assert refreshed.display_name == "Trent"


def test_get_by_username_returns_none_when_absent(conn) -> None:
    assert get_by_username(conn, "nobody") is None


def test_get_by_id_returns_the_user(conn) -> None:
    created = create(conn, username="frank", password_hash="h", role="admin")
    fetched = get_by_id(conn, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.username == "frank"


def test_get_by_id_returns_none_when_absent(conn) -> None:
    assert get_by_id(conn, 999999) is None


def test_user_carries_password_hash(conn) -> None:
    """The User dataclass exposes password_hash for the login path."""
    create(conn, username="grace", password_hash="secret-hash", role="member")
    fetched = get_by_username(conn, "grace")
    assert fetched is not None
    assert fetched.password_hash == "secret-hash"


def test_create_initial_admin_inserts_on_empty_table(conn) -> None:
    """create_initial_admin returns a User when the users table is empty."""
    user = create_initial_admin(
        conn,
        username="henry",
        password_hash="h-hash",
        display_name="Henry",
        email="henry@example.com",
    )
    assert isinstance(user, User)
    assert user.id > 0
    assert user.username == "henry"
    assert user.role == "admin"
    assert user.status == "active"


def test_create_initial_admin_returns_none_when_user_already_exists(conn) -> None:
    """create_initial_admin returns None when the users table is non-empty."""
    create(conn, username="first", password_hash="h", role="admin")
    result = create_initial_admin(
        conn,
        username="second",
        password_hash="h2",
    )
    assert result is None
    # Only the original row exists — no second insert happened.
    (count,) = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    assert count == 1
