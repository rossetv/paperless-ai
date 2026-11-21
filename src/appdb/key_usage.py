"""Per-API-key daily LLM token usage, the ``api_key_usage`` table.

One row per ``(api_key_id, usage_date)`` backs ``SEARCH_KEY_DAILY_TOKEN_QUOTA``
(see :mod:`search.spend_quota`). Untouched while the quota is disabled.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import structlog

from appdb.connection import transaction

log = structlog.get_logger(__name__)


def utc_today() -> str:
    """Return today's UTC calendar date as an ISO ``YYYY-MM-DD`` string.

    The quota resets at UTC midnight only because a new date starts a new,
    empty bucket; there is no reset job.
    """
    return datetime.now(timezone.utc).date().isoformat()


def get_tokens_used(conn: sqlite3.Connection, api_key_id: int, usage_date: str) -> int:
    """Return the tokens *api_key_id* used on *usage_date*, or ``0`` if none."""
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

    The upsert increments in SQL under ``BEGIN IMMEDIATE``, so concurrent
    recorders cannot lose each other's delta. A no-op when both are ``0``, so
    no empty bucket is inserted.
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
