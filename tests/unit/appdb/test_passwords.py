"""Tests for appdb.passwords — argon2id password hashing.

Covers the password contract: a hash verifies against its own password;
the wrong password fails; the hash is salted (two hashes of the same
password differ); a garbage hash string fails closed (returns False, never
raises); the hash is an argon2id encoded string.
"""

from __future__ import annotations

from appdb.passwords import hash_password, verify_password


def test_a_password_verifies_against_its_own_hash() -> None:
    """A password verifies against the hash produced from it."""
    encoded = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded) is True


def test_the_wrong_password_fails_verification() -> None:
    """A different password does not verify against the hash."""
    encoded = hash_password("correct horse battery staple")
    assert verify_password("wrong password", encoded) is False


def test_two_hashes_of_the_same_password_differ() -> None:
    """Hashing is salted, so the same password yields distinct hashes."""
    first = hash_password("repeated-password")
    second = hash_password("repeated-password")
    assert first != second


def test_both_salted_hashes_still_verify() -> None:
    """Each salted hash of one password still verifies against that password."""
    password = "repeated-password"
    assert verify_password(password, hash_password(password)) is True
    assert verify_password(password, hash_password(password)) is True


def test_verify_returns_false_for_a_garbage_hash() -> None:
    """A malformed hash string fails closed — returns False, never raises."""
    assert verify_password("any-password", "not-an-argon2-hash") is False


def test_verify_returns_false_for_an_empty_hash() -> None:
    """An empty hash string fails closed."""
    assert verify_password("any-password", "") is False


def test_the_hash_is_argon2id() -> None:
    """The encoded hash uses the argon2id variant."""
    encoded = hash_password("a-password")
    assert encoded.startswith("$argon2id$")


def test_an_empty_password_can_be_hashed_and_verified() -> None:
    """Hashing does not itself reject an empty password (length is the
    caller's validation concern); an empty password round-trips."""
    encoded = hash_password("")
    assert verify_password("", encoded) is True
    assert verify_password("x", encoded) is False
