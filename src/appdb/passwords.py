"""Argon2id password hashing for the application database.

Two thin wrappers over ``argon2-cffi``'s :class:`~argon2.PasswordHasher`:
:func:`hash_password` produces a salted argon2id encoded string for storage
in ``users.password_hash``, and :func:`verify_password` checks a candidate
password against a stored hash.

Argon2id is the chosen scheme (spec §2, "Password hashing"): memory-hard, so
brute-forcing a leaked hash is expensive even on a GPU. ``PasswordHasher``'s
defaults are the library's current recommended cost parameters; they are not
re-tuned here — a config knob for password cost is a footgun, not a feature.

:func:`verify_password` fails closed: any malformed stored hash, or any
mismatch, returns ``False`` and never propagates an exception to the caller,
so a corrupt row cannot turn a failed login into a 500.

Allowed deps: argon2. Forbidden: store, search, daemon packages, FastAPI.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

# A single module-level hasher with the library's recommended defaults. It is
# stateless and thread-safe, so one shared instance serves every caller.
_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """Return a salted argon2id hash of *password* for storage.

    A fresh random salt is generated per call, so hashing the same password
    twice yields two different encoded strings — both of which still verify.
    Validating the password's length or content is the caller's job; this
    function hashes whatever it is given.

    Args:
        password: The plaintext password to hash.

    Returns:
        The argon2id encoded hash string (salt and parameters embedded),
        suitable for ``users.password_hash``.
    """
    return _HASHER.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Return whether *password* matches *encoded_hash*.

    Fails closed: a wrong password, a malformed or empty *encoded_hash*, or
    any internal argon2 error all yield ``False``. The function never raises
    to its caller, so a corrupt stored hash degrades a login to a clean
    failure rather than an unhandled 500.

    Args:
        password: The candidate plaintext password.
        encoded_hash: The stored argon2id encoded hash to check against.

    Returns:
        ``True`` only when *password* hashes to *encoded_hash*.
    """
    try:
        return _HASHER.verify(encoded_hash, password)
    except (InvalidHashError, Argon2Error):
        # InvalidHashError: the stored string is not a valid argon2 hash.
        # Argon2Error (covers VerifyMismatchError): the password is wrong.
        return False
