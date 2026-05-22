"""Tests for search.sessions — opaque session tokens and the CurrentUser type.

Covers the token primitives: new_token yields a high-entropy URL-safe string;
two tokens differ; hash_token is SHA-256 hex, deterministic, and a different
token hashes differently. Also the cookie-TTL selection (remember vs not) and
the CurrentUser dataclass shape.
"""

from __future__ import annotations

from search.sessions import (
    REMEMBER_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    CurrentUser,
    cookie_ttl_seconds,
    hash_token,
    new_token,
)


def test_new_token_is_non_empty(self_unused=None) -> None:
    assert len(new_token()) > 0


def test_two_tokens_differ() -> None:
    """Tokens are random — two consecutive tokens are not equal."""
    assert new_token() != new_token()


def test_new_token_is_url_safe() -> None:
    """The token contains only URL-safe characters (cookie-safe)."""
    token = new_token()
    allowed = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    assert set(token) <= allowed


def test_new_token_has_substantial_entropy() -> None:
    """A 32-byte token base64-encodes to at least 40 characters."""
    assert len(new_token()) >= 40


def test_hash_token_is_sha256_hex() -> None:
    """hash_token returns a 64-character lowercase hex digest."""
    digest = hash_token("some-token")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_hash_token_is_deterministic() -> None:
    """The same token always hashes to the same digest."""
    assert hash_token("repeat") == hash_token("repeat")


def test_hash_token_differs_for_different_tokens() -> None:
    """Different tokens hash to different digests."""
    assert hash_token("token-a") != hash_token("token-b")


def test_hash_token_matches_known_sha256() -> None:
    """hash_token is a plain SHA-256 of the UTF-8 token bytes."""
    import hashlib

    assert hash_token("hello") == hashlib.sha256(b"hello").hexdigest()


def test_cookie_ttl_uses_remember_ttl_when_remember_is_true() -> None:
    assert cookie_ttl_seconds(remember=True) == REMEMBER_TTL_SECONDS


def test_cookie_ttl_uses_session_ttl_when_remember_is_false() -> None:
    assert cookie_ttl_seconds(remember=False) == SESSION_TTL_SECONDS


def test_remember_ttl_is_seven_days() -> None:
    assert REMEMBER_TTL_SECONDS == 604800


def test_session_ttl_is_eight_hours() -> None:
    assert SESSION_TTL_SECONDS == 28800


def test_current_user_carries_id_username_and_role() -> None:
    user = CurrentUser(id=7, username="alice", role="admin")
    assert user.id == 7
    assert user.username == "alice"
    assert user.role == "admin"
