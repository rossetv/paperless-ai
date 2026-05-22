"""Credential authentication for the search server's login endpoint.

:func:`authenticate` looks up a user by username and verifies the supplied
password against the stored argon2id hash. It deliberately does **not**
inspect the account status: the login handler does that itself, so it can
return a distinct ``403`` for a suspended account rather than folding it into
the generic ``401``.

A missing user still triggers a password verification against a throwaway
hash, so a request for an unknown username takes the same time as one for a
known username — the response does not leak which usernames exist through a
timing side channel.

Allowed deps: appdb (users, passwords). Forbidden: FastAPI, store, daemons.
"""

from __future__ import annotations

import sqlite3

from appdb import users as user_store
from appdb.passwords import hash_password, verify_password
from appdb.users import User

# A fixed argon2id hash verified against when the username is unknown, so the
# unknown-username path costs the same as the known-username path. The
# plaintext is irrelevant — no real password is ever checked against it.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> User | None:
    """Return the :class:`User` for valid credentials, else ``None``.

    Looks the user up by *username* and verifies *password* against their
    stored argon2id hash. Returns ``None`` when the username is unknown or
    the password is wrong. The account status is *not* checked here.

    Args:
        conn: An open ``app.db`` connection.
        username: The submitted username.
        password: The submitted plaintext password.

    Returns:
        The matching :class:`User`, or ``None`` when authentication fails.
    """
    user = user_store.get_by_username(conn, username)
    if user is None:
        # Verify against a dummy hash anyway so timing does not reveal that
        # the username is unknown; discard the result.
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
