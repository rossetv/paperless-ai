"""Tests for search.auth — API-key and signed-cookie authentication.

Covers the fail-closed authentication contract (spec §7.3, §9.2):

- ``verify_api_key`` accepts the configured key and rejects any other.
- ``verify_api_key`` returns False (not TypeError) on non-ASCII input (I2).
- A freshly issued session token verifies against its issuing key.
- A tampered token fails verification.
- An expired token fails verification (clock advanced past the TTL).
- A token signed with a different key fails verification.
- Malformed / garbage tokens return ``False``, never raise.
- ``is_request_authenticated`` accepts a valid bearer, accepts a valid
  cookie, and rejects when both are absent or both are invalid.
- ``cookie_attributes`` sets the security flags and the Max-Age TTL.
"""

from __future__ import annotations

from tests.helpers.factories import make_settings

from search.auth import (
    cookie_attributes,
    extract_bearer,
    is_request_authenticated,
    issue_session_token,
    verify_api_key,
    verify_session_token,
)

# A deterministic clock value (Unix epoch seconds) for token tests.
_NOW = 1_700_000_000.0
_API_KEY = "the-correct-search-api-key"
_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# verify_api_key
# ---------------------------------------------------------------------------


def test_verify_api_key_accepts_the_configured_key() -> None:
    assert verify_api_key(_API_KEY, _API_KEY) is True


def test_verify_api_key_rejects_a_wrong_key() -> None:
    assert verify_api_key("a-wrong-key", _API_KEY) is False


def test_verify_api_key_rejects_an_empty_provided_key() -> None:
    assert verify_api_key("", _API_KEY) is False


def test_verify_api_key_rejects_a_key_that_is_a_prefix_of_the_configured_key() -> None:
    # A length-prefix must not pass; compare_digest is length-sensitive.
    assert verify_api_key(_API_KEY[:-1], _API_KEY) is False


def test_verify_api_key_returns_false_not_typeerror_for_non_ascii_provided() -> None:
    """verify_api_key must return False (not raise TypeError) for non-ASCII input.

    ``hmac.compare_digest`` raises ``TypeError`` when given str arguments that
    contain non-ASCII characters.  The fix encodes both sides as UTF-8 bytes
    first.  This test fails if the comparison is reverted to comparing str
    directly.
    """
    # Non-ASCII characters that would previously cause hmac.compare_digest to
    # raise TypeError when comparing str values.
    non_ascii_key = "café"
    result = verify_api_key(non_ascii_key, _API_KEY)
    assert result is False


def test_verify_api_key_returns_false_not_typeerror_for_various_non_ascii() -> None:
    """Regression: multiple non-ASCII inputs all return False without raising."""
    for bad_key in ("café", "naïve", "日本語", "éàü", "emoji🔑"):
        # Must not raise; must return False (the key is wrong, not just non-ASCII).
        assert verify_api_key(bad_key, _API_KEY) is False


# ---------------------------------------------------------------------------
# extract_bearer
# ---------------------------------------------------------------------------


def test_extract_bearer_returns_the_token_from_a_bearer_header() -> None:
    assert extract_bearer("Bearer the-token-value") == "the-token-value"


def test_extract_bearer_returns_none_for_a_missing_header() -> None:
    assert extract_bearer(None) is None


def test_extract_bearer_returns_none_for_an_empty_header() -> None:
    assert extract_bearer("") is None


def test_extract_bearer_returns_none_without_the_bearer_prefix() -> None:
    """A raw token with no 'Bearer ' prefix is not a bearer credential."""
    assert extract_bearer(_API_KEY) is None


def test_extract_bearer_is_case_sensitive_on_the_scheme() -> None:
    """The scheme must be exactly 'Bearer ' — 'bearer ' is not accepted."""
    assert extract_bearer("bearer the-token") is None


def test_extract_bearer_requires_the_separating_space() -> None:
    """'Bearer' with no trailing space is not the bearer prefix."""
    assert extract_bearer("Bearertoken") is None


def test_extract_bearer_preserves_a_token_that_contains_spaces() -> None:
    """Only the leading 'Bearer ' is stripped; the rest is the token verbatim."""
    assert extract_bearer("Bearer token with spaces") == "token with spaces"


def test_extract_bearer_returns_empty_string_for_a_bare_scheme() -> None:
    """'Bearer ' with nothing after it yields an empty token, not None."""
    assert extract_bearer("Bearer ") == ""


# ---------------------------------------------------------------------------
# issue_session_token / verify_session_token
# ---------------------------------------------------------------------------


def test_a_freshly_issued_token_verifies() -> None:
    token = issue_session_token(_API_KEY, ttl_seconds=_TTL_SECONDS, now=_NOW)
    assert verify_session_token(token, _API_KEY, now=_NOW) is True


def test_a_token_verifies_at_any_point_before_expiry() -> None:
    token = issue_session_token(_API_KEY, ttl_seconds=_TTL_SECONDS, now=_NOW)
    just_before_expiry = _NOW + _TTL_SECONDS - 1
    assert verify_session_token(token, _API_KEY, now=just_before_expiry) is True


def test_an_expired_token_fails() -> None:
    token = issue_session_token(_API_KEY, ttl_seconds=_TTL_SECONDS, now=_NOW)
    after_expiry = _NOW + _TTL_SECONDS + 1
    assert verify_session_token(token, _API_KEY, now=after_expiry) is False


def test_a_token_used_before_its_issued_at_fails() -> None:
    # A token whose issued_at is in the future relative to `now` is invalid;
    # a clock-skew or replayed-from-the-future token must not be honoured.
    token = issue_session_token(_API_KEY, ttl_seconds=_TTL_SECONDS, now=_NOW)
    assert verify_session_token(token, _API_KEY, now=_NOW - 60) is False


def test_a_tampered_token_fails() -> None:
    token = issue_session_token(_API_KEY, ttl_seconds=_TTL_SECONDS, now=_NOW)
    # Flip the final character of the token to corrupt the signature.
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert verify_session_token(tampered, _API_KEY, now=_NOW) is False


def test_a_token_signed_with_a_different_key_fails() -> None:
    token = issue_session_token("a-different-key", ttl_seconds=_TTL_SECONDS, now=_NOW)
    assert verify_session_token(token, _API_KEY, now=_NOW) is False


def test_a_token_with_a_tampered_ttl_fails() -> None:
    # The TTL is inside the signed payload; lengthening it must break the
    # signature so a client cannot grant itself an unbounded session.
    token = issue_session_token(_API_KEY, ttl_seconds=_TTL_SECONDS, now=_NOW)
    raw = _decode_token(token)
    issued_at, ttl, signature = raw.split(".", 2)
    forged_payload = f"{issued_at}.{int(ttl) + 999_999}"
    forged = _encode_token(f"{forged_payload}.{signature}")
    assert verify_session_token(forged, _API_KEY, now=_NOW) is False


def test_a_malformed_token_returns_false_not_an_exception() -> None:
    for garbage in (
        "",
        "not-base64-at-all-!!!",
        "***",
        "a.b.c",
        _encode_token("only-one-part"),
        _encode_token("two.parts"),
        _encode_token("not-a-number.3600.deadbeef"),
        _encode_token("1700000000.not-a-number.deadbeef"),
        "\x00\x01\x02",
    ):
        assert verify_session_token(garbage, _API_KEY, now=_NOW) is False


# ---------------------------------------------------------------------------
# is_request_authenticated
# ---------------------------------------------------------------------------


def test_is_request_authenticated_accepts_a_valid_bearer() -> None:
    settings = make_settings(SEARCH_API_KEY=_API_KEY)
    assert (
        is_request_authenticated(bearer=_API_KEY, cookie=None, settings=settings)
        is True
    )


def test_is_request_authenticated_accepts_a_valid_cookie() -> None:
    settings = make_settings(SEARCH_API_KEY=_API_KEY, SEARCH_SESSION_TTL="3600")
    token = issue_session_token(_API_KEY, ttl_seconds=3600, now=_NOW)
    assert (
        is_request_authenticated(
            bearer=None, cookie=token, settings=settings, now=_NOW
        )
        is True
    )


def test_is_request_authenticated_rejects_both_absent() -> None:
    settings = make_settings(SEARCH_API_KEY=_API_KEY)
    assert (
        is_request_authenticated(bearer=None, cookie=None, settings=settings)
        is False
    )


def test_is_request_authenticated_rejects_both_invalid() -> None:
    settings = make_settings(SEARCH_API_KEY=_API_KEY)
    assert (
        is_request_authenticated(
            bearer="wrong-key", cookie="garbage-token", settings=settings, now=_NOW
        )
        is False
    )


def test_is_request_authenticated_rejects_an_invalid_bearer_with_no_cookie() -> None:
    settings = make_settings(SEARCH_API_KEY=_API_KEY)
    assert (
        is_request_authenticated(bearer="wrong-key", cookie=None, settings=settings)
        is False
    )


def test_is_request_authenticated_rejects_an_expired_cookie() -> None:
    settings = make_settings(SEARCH_API_KEY=_API_KEY, SEARCH_SESSION_TTL="3600")
    token = issue_session_token(_API_KEY, ttl_seconds=3600, now=_NOW)
    assert (
        is_request_authenticated(
            bearer=None,
            cookie=token,
            settings=settings,
            now=_NOW + 3600 + 1,
        )
        is False
    )


def test_is_request_authenticated_accepts_a_valid_cookie_when_the_bearer_is_wrong() -> (
    None
):
    # Either credential being valid is sufficient — a bad bearer plus a good
    # cookie still authenticates.
    settings = make_settings(SEARCH_API_KEY=_API_KEY, SEARCH_SESSION_TTL="3600")
    token = issue_session_token(_API_KEY, ttl_seconds=3600, now=_NOW)
    assert (
        is_request_authenticated(
            bearer="wrong-key", cookie=token, settings=settings, now=_NOW
        )
        is True
    )


# ---------------------------------------------------------------------------
# cookie_attributes
# ---------------------------------------------------------------------------


def test_cookie_attributes_sets_the_security_flags() -> None:
    settings = make_settings(SEARCH_API_KEY=_API_KEY, SEARCH_SESSION_TTL="604800")
    attributes = cookie_attributes(settings)
    assert attributes["httponly"] is True
    assert attributes["secure"] is True
    assert attributes["samesite"] == "strict"
    assert attributes["path"] == "/"


def test_cookie_attributes_carries_the_session_ttl_as_max_age() -> None:
    settings = make_settings(SEARCH_API_KEY=_API_KEY, SEARCH_SESSION_TTL="604800")
    attributes = cookie_attributes(settings)
    assert attributes["max_age"] == 604800


# ---------------------------------------------------------------------------
# Helpers — encode/decode mirror search.auth's base64 wrapping for tampering
# ---------------------------------------------------------------------------


def _encode_token(raw: str) -> str:
    """URL-safe base64-encode *raw* without padding (mirrors search.auth)."""
    import base64

    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def _decode_token(token: str) -> str:
    """Reverse :func:`_encode_token`."""
    import base64

    padding = "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token + padding).decode("ascii")
