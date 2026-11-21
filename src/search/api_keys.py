"""API keys for the REST and MCP surfaces: minting, hashing, scopes, lookup.

Only the SHA-256 of a key is stored, so a database leak yields no usable
credential. A raw key is full-entropy random, so a fast hash is enough; it
needs no slow password KDF.
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

# 256 bits, the same as a session token.
_KEY_BODY_BYTES = 32

# "sk-pls-" plus 5 random characters: enough to recognise a key, nothing more.
KEY_PREFIX_LENGTH = 12

# `api` gates /api/* data routes, `mcp` gates /mcp, `admin` gates key/user
# administration. The frontend `ApiScope` type uses the same lowercase values.
SCOPE_API = "api"
SCOPE_MCP = "mcp"
SCOPE_ADMIN = "admin"

# Fixed order so equal scope sets serialise to identical strings.
_SCOPE_ORDER: tuple[str, ...] = (SCOPE_API, SCOPE_MCP, SCOPE_ADMIN)
_VALID_SCOPES: frozenset[str] = frozenset(_SCOPE_ORDER)

# last_used_at / request_count are refreshed at most this often per key, so
# authentication is not a write on every request.
_TOUCH_INTERVAL = timedelta(seconds=60)


def generate_raw_key() -> str:
    """Return a fresh ``sk-pls-<43 url-safe characters>`` key."""
    return RAW_KEY_PREFIX + secrets.token_urlsafe(_KEY_BODY_BYTES)


def hash_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest stored in ``api_keys.key_hash``."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def key_display_prefix(raw_key: str) -> str:
    """Return the non-secret prefix the UI shows, e.g. ``sk-pls-AbC1…``."""
    return raw_key[:KEY_PREFIX_LENGTH]


def serialise_scopes(scopes: Iterable[str]) -> str:
    """Return *scopes* deduplicated, in canonical order, e.g. ``"api,mcp"``.

    Raises:
        ValueError: *scopes* is empty or contains an unknown scope.
    """
    requested = set(scopes)
    if not requested:
        raise ValueError("an API key must have at least one scope")
    unknown = requested - _VALID_SCOPES
    if unknown:
        raise ValueError(f"unknown scope(s): {sorted(unknown)}")
    return ",".join(s for s in _SCOPE_ORDER if s in requested)


def parse_scopes(scopes: str) -> frozenset[str]:
    """Return the recognised scopes in a stored scope string.

    Unknown tokens are dropped, so corrupt data authorises nothing.
    """
    tokens = {part.strip() for part in scopes.split(",")}
    return frozenset(tokens & _VALID_SCOPES)


def should_touch(last_used_at: str | None) -> bool:
    """Return whether the key's usage stats are due a refresh.

    An unparseable timestamp counts as due, so corrupt data cannot freeze usage
    tracking.
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

    *owner_role* is the owner's current role; a key never grants more than it.
    *owner_display_name* is the search "who is asking" signal.
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

    An unparseable expiry counts as expired (fail closed). A tz-naive value,
    e.g. from a hand-edited row, is read as UTC so the comparison cannot raise.
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

    Every rejection (unknown, revoked, expired, owner missing or suspended)
    returns ``None`` rather than raising, so a hostile request cannot cause a
    500. The owner's current role is read, so demoting an owner reins in their
    keys at once.
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
