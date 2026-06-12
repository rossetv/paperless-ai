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
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from appdb import api_keys as key_store
from appdb import users as user_store

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


@dataclass(frozen=True, slots=True)
class ResolvedKey:
    """A presented API key resolved to an authenticated identity.

    The output of :func:`resolve_api_key` — everything the auth layer needs
    to authorise the request: which key it was (for usage tracking), who
    owns it, the owner's *current* role (which bounds the key's reach), and
    the scopes granted to the key itself.

    Attributes:
        api_key_id: The id of the matched ``api_keys`` row.
        owner_user_id: The owning user's id.
        owner_username: The owning user's login name, for logging/display.
        owner_role: The owner's current role. A key never grants more than
            its owner's role allows.
        owner_display_name: The owner's optional display name (the search "who
            is asking" signal), or None when the account has no display name.
        scopes: The frozenset of scopes parsed from the key's ``scopes``
            column.
        last_used_at: The key's stored ``last_used_at`` (or ``None``), so the
            caller can decide whether a usage "touch" is due.
    """

    api_key_id: int
    owner_user_id: int
    owner_username: str
    owner_role: str
    owner_display_name: str | None
    scopes: frozenset[str]
    last_used_at: str | None


def _is_expired(expires_at: str | None) -> bool:
    """Return whether *expires_at* is set and already in the past.

    A key with no expiry (``None``) never expires. An unparseable expiry is
    treated as expired — corrupt data must fail closed, not grant access.

    A stored expiry may be tz-naive (a legacy or hand-edited row, e.g.
    ``"2099-01-01T00:00:00"``); a naive value is coerced to UTC before the
    comparison so it can never raise ``TypeError`` (offset-naive vs.
    offset-aware) and brick the key. The broad ``(ValueError, TypeError)``
    catch keeps the "never raises / fail-closed" contract of
    :func:`resolve_api_key` for any value the column might hold.
    """
    if expires_at is None:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return datetime.now(timezone.utc) >= expiry


def resolve_api_key(
    conn: sqlite3.Connection, raw_key: str | None
) -> ResolvedKey | None:
    """Resolve a presented raw API key to a :class:`ResolvedKey`, or ``None``.

    The bearer-auth lookup. It returns ``None`` — never raises — for every
    rejection, so a hostile request cannot trigger a 500:

    - *raw_key* is ``None`` (no credential presented);
    - no ``api_keys`` row has the matching ``key_hash``;
    - the key has been revoked (``revoked_at`` set);
    - the key has expired (``expires_at`` in the past);
    - the owning user is missing or suspended.

    On success the returned :class:`ResolvedKey` carries the owner's
    *current* role, so demoting or suspending an owner immediately reins in
    every key they own.

    Args:
        conn: The open ``app.db`` connection.
        raw_key: The bearer token presented by the request, or ``None``.

    Returns:
        A :class:`ResolvedKey` when the key is live and usable, else
        ``None``.
    """
    if raw_key is None:
        return None

    record = key_store.get_by_hash(conn, hash_key(raw_key))
    if record is None:
        return None
    if record.revoked_at is not None:
        return None
    if _is_expired(record.expires_at):
        return None

    owner = user_store.get_by_id(conn, record.owner_user_id)
    if owner is None or owner.status != "active":
        # A deleted owner cascades the key away, but a suspended owner does
        # not — guard it here so a suspended owner's keys go dead too.
        return None

    return ResolvedKey(
        api_key_id=record.id,
        owner_user_id=owner.id,
        owner_username=owner.username,
        owner_role=owner.role,
        owner_display_name=owner.display_name,
        scopes=parse_scopes(record.scopes),
        last_used_at=record.last_used_at,
    )
