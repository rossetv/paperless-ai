"""Tests for search.auth — bearer parsing, legacy API-key auth, and RBAC.

Wave 1 replaced the stateless signed-cookie scheme with database-backed
sessions; the session lifecycle is tested in test_sessions*.py. This file
covers what remains in search.auth:

- extract_bearer parses the Authorization header, case-sensitively.
- verify_api_key is a constant-time compare; an empty configured key never
  matches.
- legacy_api_key_user resolves a valid legacy bearer to a synthetic admin.
- authorise_role ranks readonly < member < admin and fails closed on an
  unknown role.
"""

from __future__ import annotations

from search.auth import (
    LEGACY_API_KEY_USER,
    authorise_role,
    extract_bearer,
    legacy_api_key_user,
    verify_api_key,
)

_API_KEY = "the-correct-search-api-key"


# ---------------------------------------------------------------------------
# extract_bearer
# ---------------------------------------------------------------------------


def test_extract_bearer_returns_the_token() -> None:
    assert extract_bearer("Bearer the-token-value") == "the-token-value"


def test_extract_bearer_returns_none_for_a_missing_header() -> None:
    assert extract_bearer(None) is None


def test_extract_bearer_returns_none_for_an_empty_header() -> None:
    assert extract_bearer("") is None


def test_extract_bearer_returns_none_without_the_prefix() -> None:
    assert extract_bearer(_API_KEY) is None


def test_extract_bearer_is_case_sensitive() -> None:
    assert extract_bearer("bearer the-token") is None


def test_extract_bearer_requires_the_separating_space() -> None:
    assert extract_bearer("Bearertoken") is None


def test_extract_bearer_preserves_inner_spaces() -> None:
    assert extract_bearer("Bearer token with spaces") == "token with spaces"


def test_extract_bearer_returns_empty_for_a_bare_scheme() -> None:
    assert extract_bearer("Bearer ") == ""


# ---------------------------------------------------------------------------
# verify_api_key
# ---------------------------------------------------------------------------


def test_verify_api_key_accepts_the_configured_key() -> None:
    assert verify_api_key(_API_KEY, _API_KEY) is True


def test_verify_api_key_rejects_a_wrong_key() -> None:
    assert verify_api_key("a-wrong-key", _API_KEY) is False


def test_verify_api_key_rejects_an_empty_provided_key() -> None:
    assert verify_api_key("", _API_KEY) is False


def test_verify_api_key_rejects_a_prefix_of_the_key() -> None:
    """compare_digest is length-sensitive — a prefix must not pass."""
    assert verify_api_key(_API_KEY[:-1], _API_KEY) is False


def test_verify_api_key_rejects_everything_when_configured_key_is_empty() -> None:
    """A deployment with no legacy key is never unlocked by a bearer."""
    assert verify_api_key("", "") is False
    assert verify_api_key("anything", "") is False


def test_verify_api_key_returns_false_for_non_ascii_not_typeerror() -> None:
    """Non-ASCII input must return False, never raise TypeError."""
    for bad in ("café", "naïve", "日本語", "emoji🔑"):
        assert verify_api_key(bad, _API_KEY) is False


# ---------------------------------------------------------------------------
# legacy_api_key_user
# ---------------------------------------------------------------------------


def test_legacy_api_key_user_returns_the_synthetic_admin_on_a_match() -> None:
    user = legacy_api_key_user(_API_KEY, _API_KEY)
    assert user is LEGACY_API_KEY_USER
    assert user.role == "admin"
    assert user.id == 0


def test_legacy_api_key_user_returns_none_for_a_wrong_key() -> None:
    assert legacy_api_key_user("wrong", _API_KEY) is None


def test_legacy_api_key_user_returns_none_for_a_missing_bearer() -> None:
    assert legacy_api_key_user(None, _API_KEY) is None


def test_legacy_api_key_user_returns_none_when_no_key_configured() -> None:
    assert legacy_api_key_user("anything", "") is None


# ---------------------------------------------------------------------------
# authorise_role
# ---------------------------------------------------------------------------


def test_admin_satisfies_every_requirement() -> None:
    assert authorise_role("admin", "readonly") is True
    assert authorise_role("admin", "member") is True
    assert authorise_role("admin", "admin") is True


def test_member_satisfies_member_and_below_but_not_admin() -> None:
    assert authorise_role("member", "readonly") is True
    assert authorise_role("member", "member") is True
    assert authorise_role("member", "admin") is False


def test_readonly_satisfies_only_readonly() -> None:
    assert authorise_role("readonly", "readonly") is True
    assert authorise_role("readonly", "member") is False
    assert authorise_role("readonly", "admin") is False


def test_authorise_role_fails_closed_for_an_unknown_caller_role() -> None:
    assert authorise_role("wizard", "readonly") is False


def test_authorise_role_fails_closed_for_an_unknown_requirement() -> None:
    """An unknown required role is a bug; it must never authorise anyone."""
    assert authorise_role("admin", "superuser") is False
