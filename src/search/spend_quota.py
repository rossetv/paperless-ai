"""Per-API-key daily LLM-token quota for the REST search endpoints and MCP tools.

One query is bounded by its LLM budget, but nothing else bounds cumulative
spend: a leaked API key could run queries back to back. :func:`check_quota`
runs before the pipeline and :func:`record_usage` after it.

With the quota at ``0`` (the default) or a cookie caller, both steps do no
I/O. The cap is soft: the check is repeated once a search slot is held, so the
overshoot is at most one query per slot, which is fine for a spend ceiling and
avoids a reservation. A new UTC date is a new, empty bucket.
"""

from __future__ import annotations

from contextvars import ContextVar

import structlog

from appdb import key_usage
from appdb.connection import connect
from search.offload import run_blocking

log = structlog.get_logger(__name__)

# Carries the API-key id from the MCP auth middleware (raw ASGI, no dependency
# injection) to the tool handlers. ``None`` for a cookie caller.
mcp_api_key_id: ContextVar[int | None] = ContextVar("mcp_api_key_id", default=None)


class QuotaExceededError(Exception):
    """An API key has reached its daily LLM-token quota.

    REST maps it to a 429 with ``Retry-After``; MCP to a tool error.
    """

    def __init__(self, *, quota: int, tokens_used: int) -> None:
        self.quota = quota
        self.tokens_used = tokens_used
        super().__init__(
            f"daily LLM token quota of {quota} reached "
            f"({tokens_used} tokens used today)"
        )


def _is_quota_active(quota: int, api_key_id: int | None) -> bool:
    """Return whether the quota is enabled and the caller is an API key."""
    return quota > 0 and api_key_id is not None


async def check_quota(*, api_key_id: int | None, quota: int, app_db_path: str) -> None:
    """Raise :class:`QuotaExceededError` when the key has used up *quota* today.

    ``quota`` is ``SEARCH_KEY_DAILY_TOKEN_QUOTA``; ``0`` disables the check.
    """
    if not _is_quota_active(quota, api_key_id):
        return
    # Narrows the type for the closure; _is_quota_active guarantees it.
    assert api_key_id is not None
    tokens_used = await run_blocking(lambda: _read_tokens_used(app_db_path, api_key_id))
    if tokens_used >= quota:
        log.warning(
            "search.quota_exceeded",
            api_key_id=api_key_id,
            quota=quota,
            tokens_used=tokens_used,
        )
        raise QuotaExceededError(quota=quota, tokens_used=tokens_used)


async def record_usage(
    *, api_key_id: int | None, quota: int, tokens: int, app_db_path: str
) -> None:
    """Add a completed query's tokens to the API key's bucket for today.

    Best-effort: a database error is logged and swallowed, so recording can
    never fail a search that already succeeded.
    """
    if not _is_quota_active(quota, api_key_id):
        return
    assert api_key_id is not None
    try:
        await run_blocking(lambda: _write_usage(app_db_path, api_key_id, tokens))
    except Exception:
        # The result is already built; the soft cap tolerates a lost record.
        log.exception("search.quota_record_failed", api_key_id=api_key_id)


def record_usage_blocking(
    *, api_key_id: int | None, quota: int, tokens: int, app_db_path: str
) -> None:
    """Synchronous :func:`record_usage`, for the streaming search's worker thread.

    Uses its own connection, never the request's, so a client disconnect that
    closes the request connection cannot race this write.
    """
    if not _is_quota_active(quota, api_key_id):
        return
    assert api_key_id is not None
    try:
        _write_usage(app_db_path, api_key_id, tokens)
    except Exception:
        # Never break a stream already in flight over a lost record.
        log.exception("search.quota_record_failed", api_key_id=api_key_id)


def _read_tokens_used(app_db_path: str, api_key_id: int) -> int:
    """Read the key's tokens used today on a fresh connection."""
    conn = connect(app_db_path)
    try:
        return key_usage.get_tokens_used(conn, api_key_id, key_usage.utc_today())
    finally:
        conn.close()


def _write_usage(app_db_path: str, api_key_id: int, tokens: int) -> None:
    """Add the query's tokens to today's bucket on a fresh connection."""
    conn = connect(app_db_path)
    try:
        key_usage.add_usage(
            conn, api_key_id, key_usage.utc_today(), tokens=tokens, calls=1
        )
    finally:
        conn.close()
