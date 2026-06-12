"""Per-API-key daily LLM-spend usage in the application database.

This module owns the ``api_key_usage`` table (app.db migration v7) — the
storage behind the per-API-key daily token quota (``SEARCH_KEY_DAILY_TOKEN_QUOTA``).
One row per ``(api_key_id, usage_date)`` pair holds the cumulative LLM
``tokens`` and completed-query ``calls`` a key consumed on that UTC calendar
day. The search server's spend-quota guard (:mod:`search.spend_quota`) reads
the day's total before a query runs and records the query's tokens after it
finishes; higher layers never write ``api_key_usage`` SQL themselves.

Two functions form the contract:

- :func:`get_tokens_used` — the day's running token total for a key (``0`` when
  no row exists yet), the value the pre-request check compares against the
  quota.
- :func:`add_usage` — an upsert that advances both counters in place, so a
  day's bucket grows rather than stacking a row per query.

The quota is only ever consulted when an operator sets a positive
``SEARCH_KEY_DAILY_TOKEN_QUOTA``; with the default (disabled) quota neither
function is called and this table is never touched.

Allowed deps: sqlite3, datetime, structlog. Forbidden: store, search, daemon
packages, FastAPI.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import structlog

from appdb.connection import transaction

log = structlog.get_logger(__name__)


def utc_today() -> str:
    """Return today's UTC calendar date as an ISO ``YYYY-MM-DD`` string.

    The single source of the ``usage_date`` key format, so the value written
    by :func:`add_usage` and the value read by :func:`get_tokens_used` are
    always the same shape. The quota resets at UTC midnight purely because a
    new date produces a new, empty bucket — there is no scheduled reset job.
    """
    return datetime.now(timezone.utc).date().isoformat()


def get_tokens_used(conn: sqlite3.Connection, api_key_id: int, usage_date: str) -> int:
    """Return the cumulative tokens *api_key_id* used on *usage_date*.

    Returns ``0`` when no row exists for that key and date — an absent bucket
    is an unused one. This is a single indexed lookup on the composite primary
    key, the read the pre-request quota check performs.

    Args:
        conn: An open, migrated ``app.db`` connection.
        api_key_id: The id of the key whose usage to read.
        usage_date: The UTC calendar date (``YYYY-MM-DD``) to read, as produced
            by :func:`utc_today`.

    Returns:
        The cumulative token count for that key on that day, or ``0``.
    """
    row = conn.execute(
        "SELECT tokens FROM api_key_usage WHERE api_key_id = ? AND usage_date = ?",
        (api_key_id, usage_date),
    ).fetchone()
    return int(row["tokens"]) if row is not None else 0


def add_usage(
    conn: sqlite3.Connection,
    api_key_id: int,
    usage_date: str,
    *,
    tokens: int,
    calls: int,
) -> None:
    """Add *tokens* and *calls* to *api_key_id*'s bucket for *usage_date*.

    Upserts on the ``(api_key_id, usage_date)`` primary key: the first write of
    the day inserts the bucket, every later write of the same day advances both
    counters in place (``tokens = tokens + excluded.tokens``,
    ``calls = calls + excluded.calls``). The whole read-modify-write runs inside
    a ``BEGIN IMMEDIATE`` transaction (:func:`appdb.connection.transaction`), so
    two concurrent recorders each add their delta without losing one another's —
    the upsert's ``+ excluded`` is the atomic increment, the immediate write
    lock serialises the two transactions.

    A no-op when both *tokens* and *calls* are ``0`` — a query that somehow
    produced no usable token count records nothing rather than inserting an
    empty bucket.

    Args:
        conn: An open, migrated ``app.db`` connection.
        api_key_id: The id of the key that consumed the spend. Must reference an
            existing ``api_keys`` row — the foreign key is enforced.
        usage_date: The UTC calendar date (``YYYY-MM-DD``) to record against, as
            produced by :func:`utc_today`.
        tokens: The completed query's total LLM token count to add.
        calls: The number of completed queries to add (normally ``1``).
    """
    if tokens == 0 and calls == 0:
        return
    with transaction(conn):
        conn.execute(
            "INSERT INTO api_key_usage (api_key_id, usage_date, tokens, calls) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(api_key_id, usage_date) DO UPDATE SET "
            "tokens = tokens + excluded.tokens, "
            "calls = calls + excluded.calls",
            (api_key_id, usage_date, tokens, calls),
        )
