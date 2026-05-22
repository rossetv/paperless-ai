"""API-key primitives for the search server (web-redesign §5).

Wave 3 added programmatic API keys for the REST and MCP surfaces. This module
owns the pieces that are *not* the database table (:mod:`appdb.api_keys`):

- :func:`generate_raw_key` mints a fresh ``sk-pls-<random>`` key.
- :func:`hash_key` is the SHA-256 the database stores — the raw key is never
  persisted, so a database leak yields no usable credential.
- :func:`key_display_prefix` extracts the short, non-secret display prefix.
- The ``SCOPE_*`` constants and :func:`parse_scopes` / :func:`serialise_scopes`
  are the scope model: a key carries a subset of ``api``/``mcp``/``admin``.
- :func:`should_touch` throttles the usage-tracking write.
- :class:`ResolvedKey` (defined here) and :func:`resolve_api_key` (added in
  the next task) turn a presented raw key into an authenticated identity.

Like a session token, a raw key is full-entropy random, so SHA-256 — a fast
hash, not a slow password KDF — is the correct one-way mapping (the same
reasoning as :func:`search.sessions.hash_token`).

Allowed deps: stdlib (secrets, hashlib, datetime), appdb (api_keys, users).
Forbidden: FastAPI, sqlite3 SQL, store, daemon packages.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

# The literal prefix every raw key carries. Lets a leaked string be spotted
# as a Paperless-AI key, and namespaces it from other "sk-" credentials.
RAW_KEY_PREFIX = "sk-pls-"

# Entropy of the random body, in bytes. 32 bytes (256 bits) is well beyond
# brute force — the same budget as a session token.
_KEY_BODY_BYTES = 32

# How many leading characters of the raw key are kept as the display prefix.
# 12 covers "sk-pls-" (7) plus the first 5 random characters — enough for a
# human to recognise a key without revealing anything useful.
KEY_PREFIX_LENGTH = 12

# The three scopes (web-redesign §5). `api` gates /api/* data routes; `mcp`
# gates /mcp; `admin` gates key/user administration. Lowercase is the
# canonical wire form — the frontend `ApiScope` type uses the same values,
# so no case transform exists anywhere.
SCOPE_API = "api"
SCOPE_MCP = "mcp"
SCOPE_ADMIN = "admin"

# The canonical scope order, so a serialised scope string is stable and two
# equal scope sets always produce byte-identical stored values.
_SCOPE_ORDER: tuple[str, ...] = (SCOPE_API, SCOPE_MCP, SCOPE_ADMIN)
_VALID_SCOPES: frozenset[str] = frozenset(_SCOPE_ORDER)

# The usage-tracking throttle. last_used_at / request_count are refreshed at
# most once per key per this interval, so authentication is not a write on
# every request (the same pattern as session last_seen_at).
_TOUCH_INTERVAL = timedelta(seconds=60)


def generate_raw_key() -> str:
    """Return a fresh, high-entropy raw API key.

    The value handed to the user exactly once at creation. It is never stored
    as given — :func:`hash_key` produces what the database holds.

    Returns:
        A string of the form ``sk-pls-<43 url-safe characters>``.
    """
    return RAW_KEY_PREFIX + secrets.token_urlsafe(_KEY_BODY_BYTES)


def hash_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of *raw_key*.

    This is the value stored in ``api_keys.key_hash`` and the value the
    bearer-auth path computes from a presented key to look it up.

    Args:
        raw_key: The full ``sk-pls-...`` key.

    Returns:
        The 64-character lowercase hex SHA-256 digest.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def key_display_prefix(raw_key: str) -> str:
    """Return the short, non-secret display prefix of *raw_key*.

    The first :data:`KEY_PREFIX_LENGTH` characters — stored in
    ``api_keys.key_prefix`` so the UI can show ``sk-pls-AbC1…`` without ever
    holding the secret. A string shorter than the cap is returned whole
    (only possible for malformed input).

    Args:
        raw_key: The full raw key.
    """
    return raw_key[:KEY_PREFIX_LENGTH]


def serialise_scopes(scopes: Iterable[str]) -> str:
    """Return *scopes* as a canonical, comma-separated string for storage.

    Deduplicates, validates every scope against :data:`_VALID_SCOPES`, and
    emits them in :data:`_SCOPE_ORDER` so the stored string is stable.

    Args:
        scopes: The scopes to grant the key.

    Returns:
        A comma-separated scope string, e.g. ``"api,mcp"``.

    Raises:
        ValueError: *scopes* is empty (a scope-less key is useless), or
            contains a value outside ``api``/``mcp``/``admin``.
    """
    requested = set(scopes)
    if not requested:
        raise ValueError("an API key must have at least one scope")
    unknown = requested - _VALID_SCOPES
    if unknown:
        raise ValueError(f"unknown scope(s): {sorted(unknown)}")
    return ",".join(s for s in _SCOPE_ORDER if s in requested)


def parse_scopes(scopes: str) -> frozenset[str]:
    """Return the set of valid scopes encoded in *scopes*.

    Splits on commas, trims whitespace, and keeps only tokens in
    :data:`_VALID_SCOPES`. An empty string, or one of pure junk, yields the
    empty set — a key with no recognised scope authorises nothing, which is
    the correct fail-closed behaviour for corrupt stored data.

    Args:
        scopes: The comma-separated scope string from ``api_keys.scopes``.

    Returns:
        The frozenset of recognised scopes.
    """
    tokens = {part.strip() for part in scopes.split(",")}
    return frozenset(tokens & _VALID_SCOPES)


def should_touch(last_used_at: str | None) -> bool:
    """Return whether the key's usage stats are due a refresh.

    ``True`` when the key has never been used (*last_used_at* is ``None``),
    when the stored timestamp is older than :data:`_TOUCH_INTERVAL`, or when
    it cannot be parsed (corrupt data must not freeze usage tracking).
    ``False`` only when the timestamp is recent — so the caller skips the
    database write.

    Args:
        last_used_at: The stored ``last_used_at`` ISO-8601 string, or
            ``None``.
    """
    if last_used_at is None:
        return True
    try:
        stamped = datetime.fromisoformat(last_used_at)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - stamped >= _TOUCH_INTERVAL
