"""Argon2id password hashing.

Argon2id is memory-hard, so brute-forcing a leaked hash is expensive even on a
GPU. The library's recommended cost parameters are used as-is; a config knob
for password cost would be a footgun.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

# Stateless and thread-safe, so one shared instance serves every caller.
_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """Return a salted argon2id hash of *password*, with its parameters embedded.

    Validating the password is the caller's job.
    """
    return _HASHER.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Return whether *password* matches *encoded_hash*.

    Fails closed and never raises, so a corrupt stored hash turns a login into
    a clean failure rather than a 500.
    """
    try:
        return _HASHER.verify(encoded_hash, password)
    except (InvalidHashError, Argon2Error):
        # Argon2Error covers VerifyMismatchError (wrong password).
        return False
