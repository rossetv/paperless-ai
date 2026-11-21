"""Credential check for the login endpoint."""

from __future__ import annotations

import sqlite3

from appdb import users as user_store
from appdb.passwords import hash_password, verify_password
from appdb.users import User

# Verified against when the username is unknown, so that path costs the same
# as a real check and timing does not reveal which usernames exist.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> User | None:
    """Return the :class:`User` for valid credentials, else ``None``.

    Account status is not checked here: the login handler does that so it can
    return a distinct 403 for a suspended account instead of the generic 401.
    """
    user = user_store.get_by_username(conn, username)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
