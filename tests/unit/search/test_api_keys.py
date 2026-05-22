"""Tests for search.api_keys — raw-key generation, hashing, scopes.

Covers: generate_raw_key yields an sk-pls-prefixed high-entropy string; two
keys differ; hash_key is SHA-256 hex and deterministic; key_prefix is the
documented length; the scope constants and parse_scopes/serialise_scopes
round-trip and reject junk; should_touch throttles on the stored timestamp.
"""

from __future__ import annotations

import hashlib

import pytest

from search.api_keys import (
    KEY_PREFIX_LENGTH,
    RAW_KEY_PREFIX,
    SCOPE_ADMIN,
    SCOPE_API,
    SCOPE_MCP,
    generate_raw_key,
    hash_key,
    key_display_prefix,
    parse_scopes,
    serialise_scopes,
    should_touch,
)


def test_generate_raw_key_has_the_sk_pls_prefix() -> None:
    assert generate_raw_key().startswith(RAW_KEY_PREFIX)


def test_raw_key_prefix_constant_is_sk_pls() -> None:
    assert RAW_KEY_PREFIX == "sk-pls-"


def test_two_generated_keys_differ() -> None:
    assert generate_raw_key() != generate_raw_key()


def test_generated_key_has_substantial_entropy() -> None:
    """sk-pls- + a 32-byte token base64 => well over 40 characters."""
    assert len(generate_raw_key()) >= 47


def test_generated_key_is_url_safe_after_the_prefix() -> None:
    body = generate_raw_key()[len(RAW_KEY_PREFIX):]
    allowed = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    assert set(body) <= allowed


def test_hash_key_is_sha256_hex() -> None:
    digest = hash_key("sk-pls-something")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_hash_key_is_deterministic() -> None:
    assert hash_key("sk-pls-repeat") == hash_key("sk-pls-repeat")


def test_hash_key_matches_plain_sha256() -> None:
    assert hash_key("sk-pls-x") == hashlib.sha256(b"sk-pls-x").hexdigest()


def test_hash_key_differs_for_different_keys() -> None:
    assert hash_key("sk-pls-a") != hash_key("sk-pls-b")


def test_key_display_prefix_is_the_documented_length() -> None:
    raw = generate_raw_key()
    prefix = key_display_prefix(raw)
    assert len(prefix) == KEY_PREFIX_LENGTH
    assert raw.startswith(prefix)


def test_key_display_prefix_of_a_short_string_returns_the_whole_string() -> None:
    assert key_display_prefix("sk-x") == "sk-x"


def test_scope_constants_are_the_three_documented_values() -> None:
    assert SCOPE_API == "api"
    assert SCOPE_MCP == "mcp"
    assert SCOPE_ADMIN == "admin"


def test_serialise_scopes_joins_with_commas() -> None:
    assert serialise_scopes([SCOPE_API, SCOPE_MCP]) == "api,mcp"


def test_serialise_scopes_deduplicates_and_orders(self_unused=None) -> None:
    """A canonical order makes the stored string stable and comparable."""
    assert serialise_scopes([SCOPE_MCP, SCOPE_API, SCOPE_API]) == "api,mcp"


def test_serialise_scopes_rejects_an_unknown_scope() -> None:
    with pytest.raises(ValueError, match="scope"):
        serialise_scopes(["api", "superuser"])


def test_serialise_scopes_rejects_an_empty_list() -> None:
    """A key with no scopes can do nothing — reject it at creation."""
    with pytest.raises(ValueError, match="scope"):
        serialise_scopes([])


def test_parse_scopes_splits_a_comma_string() -> None:
    assert parse_scopes("api,mcp") == frozenset({"api", "mcp"})


def test_parse_scopes_tolerates_whitespace(self_unused=None) -> None:
    assert parse_scopes(" api , mcp ") == frozenset({"api", "mcp"})


def test_parse_scopes_of_an_empty_string_is_empty() -> None:
    """A defensively empty/corrupt scope string yields no scopes — the key
    then authorises nothing (fail closed)."""
    assert parse_scopes("") == frozenset()


def test_parse_scopes_drops_unknown_tokens() -> None:
    """An unknown token in stored data is ignored, never granted."""
    assert parse_scopes("api,garbage") == frozenset({"api"})


def test_should_touch_is_true_when_never_used() -> None:
    assert should_touch(None) is True


def test_should_touch_is_false_for_a_recent_timestamp() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    assert should_touch(now) is False


def test_should_touch_is_true_for_a_stale_timestamp() -> None:
    assert should_touch("2000-01-01T00:00:00+00:00") is True


def test_should_touch_is_true_for_an_unparseable_timestamp() -> None:
    """Corrupt data must not freeze usage tracking — touch anyway."""
    assert should_touch("not-a-timestamp") is True
