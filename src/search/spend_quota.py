"""Per-API-key daily LLM-spend quota for the search endpoints.

A single query is already bounded — the per-query LLM budget caps one query's
cost and ``SEARCH_MAX_CONCURRENT`` caps simultaneous queries — but nothing
bounds *cumulative* spend, so a leaked low-privilege API key can issue unbounded
sequential queries and run up arbitrary LLM cost. This module closes that: it
caps the LLM tokens one API key may consume per UTC calendar day across both
the REST search endpoints and the MCP tools.

The contract is two steps the search surfaces (:mod:`search.routes` and
:mod:`search.mcp_server`) wrap around the pipeline:

- :func:`check_quota` — **before** the pipeline runs. When the quota is positive
  and the caller is an API key whose tokens-used-today has reached the cap, it
  raises :class:`QuotaExceededError`, so an over-quota key never spends a token.
- :func:`record_usage` — **after** the pipeline runs. It adds the completed
  query's total tokens (and one call) to the key's daily bucket.

**Disabled by default — zero overhead.** Both steps short-circuit immediately
(no database connection, no query) when the quota is ``0`` (disabled, the
default) or the caller is not an API key (a cookie/browser user, ``api_key_id``
is ``None``). A deployment that has not set a positive
``SEARCH_KEY_DAILY_TOKEN_QUOTA`` therefore pays no quota-related I/O on the
search path at all.

**Soft cap, by design.** The check, the pipeline run, and the record form a
window: two queries that pass the check concurrently can both run and slightly
overshoot the cap before either records its usage. That is acceptable for a
spend ceiling — it bounds runaway cost without the cost and complexity of a
reservation or lock. There is deliberately no per-query reservation. The cap
resets at UTC midnight purely because a new calendar date is a new, empty
bucket (see :func:`appdb.key_usage.utc_today`).

Both database steps open a short-lived ``app.db`` connection from the injected
path and run off the event loop through :func:`search.offload.run_blocking`,
mirroring the surrounding search code; :func:`record_usage` never raises a
database error up into the caller — a usage-write failure degrades to a logged
warning so a recording fault can never break an otherwise-successful search.

Allowed deps: contextvars, structlog, appdb (connection, key_usage),
    search.offload. Forbidden: fastapi, mcp, direct sqlite3/LLM/HTTP.
"""

from __future__ import annotations

from contextvars import ContextVar

import structlog

from appdb import key_usage
from appdb.connection import connect
from search.offload import run_blocking

log = structlog.get_logger(__name__)

# Carries the resolved API-key id from the MCP auth middleware (raw ASGI, no
# FastAPI dependency injection) to the MCP tool handlers that run downstream in
# the same async context — mirroring how search.identity.mcp_asker carries the
# asker. ``None`` means the request is a cookie/browser caller (not an API key),
# for which the quota never applies.
mcp_api_key_id: ContextVar[int | None] = ContextVar("mcp_api_key_id", default=None)


class QuotaExceededError(Exception):
    """An API key has reached its daily LLM-token quota.

    Raised by :func:`check_quota` before a query runs. It carries the numbers
    each surface needs to build its rejection: the REST handlers map it to an
    HTTP 429 with a ``Retry-After`` to the next UTC midnight; the MCP tools turn
    it into a tool error. It is a plain domain fault, never re-wrapped from a
    database error — it is a policy decision, not an I/O failure.

    Attributes:
        quota: The configured per-day token quota that was reached.
        tokens_used: The key's tokens-used-today at the moment of the check.
    """

    def __init__(self, *, quota: int, tokens_used: int) -> None:
        self.quota = quota
        self.tokens_used = tokens_used
        super().__init__(
            f"daily LLM token quota of {quota} reached "
            f"({tokens_used} tokens used today)"
        )


def _is_quota_active(quota: int, api_key_id: int | None) -> bool:
    """Return whether the quota applies to this request.

    The single predicate both steps share: the quota is active only when it is
    positive (an operator opted in) **and** the caller is an API key
    (``api_key_id`` is not ``None`` — a cookie/browser user is never limited).
    When this is ``False`` the caller does zero database work, which is what
    keeps the disabled default free of any search-path I/O.
    """
    return quota > 0 and api_key_id is not None


async def check_quota(*, api_key_id: int | None, quota: int, app_db_path: str) -> None:
    """Reject a request whose API key has reached its daily token quota.

    A no-op — with no database access — when the quota is disabled (``0``) or
    the caller is not an API key. Otherwise it reads the key's tokens-used-today
    off the event loop and raises :class:`QuotaExceededError` when that total
    has reached *quota*. Called before the pipeline runs, so an over-quota key
    never spends a token.

    Args:
        api_key_id: The matched ``api_keys`` row id, or ``None`` for a
            cookie/browser caller.
        quota: ``SEARCH_KEY_DAILY_TOKEN_QUOTA`` — ``0`` disables the cap.
        app_db_path: Filesystem path to ``app.db``; a short-lived connection is
            opened for the read and closed straight after.

    Raises:
        QuotaExceededError: The key's tokens-used-today is at or above *quota*.
    """
    if not _is_quota_active(quota, api_key_id):
        return
    # api_key_id is not None here (guaranteed by _is_quota_active); assert to
    # narrow the type for the closure below without a runtime branch.
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
    """Add a completed query's tokens to the API key's daily bucket.

    A no-op — with no database access — when the quota is disabled (``0``) or
    the caller is not an API key, so the disabled default writes nothing.
    Otherwise it upserts *tokens* (and one call) into the key's bucket for
    today (UTC) off the event loop.

    Best-effort: a database error while recording is logged and swallowed — a
    usage-write fault must never turn an otherwise-successful search into a
    failed request, nor break a stream mid-flight. The cap is soft, so a
    dropped record at worst lets the key slightly overshoot.

    Args:
        api_key_id: The matched ``api_keys`` row id, or ``None`` for a
            cookie/browser caller.
        quota: ``SEARCH_KEY_DAILY_TOKEN_QUOTA`` — ``0`` disables recording.
        tokens: The completed query's total LLM token count.
        app_db_path: Filesystem path to ``app.db``; a short-lived connection is
            opened for the write and closed straight after.
    """
    if not _is_quota_active(quota, api_key_id):
        return
    assert api_key_id is not None
    try:
        await run_blocking(lambda: _write_usage(app_db_path, api_key_id, tokens))
    except Exception:
        # rationale: a usage-write failure must never fail the search itself
        # (CODE_GUIDELINES §6.4) — the result is already built (or the stream is
        # already flowing). log.exception attaches the traceback (§7.5) so a
        # recurring fault on this best-effort side path stays debuggable. The
        # soft cap tolerates a lost record.
        log.exception("search.quota_record_failed", api_key_id=api_key_id)


def record_usage_blocking(
    *, api_key_id: int | None, quota: int, tokens: int, app_db_path: str
) -> None:
    """Synchronous :func:`record_usage`, for a caller already on a worker thread.

    The streaming search runs its pipeline on a worker thread and learns the
    token total there, where it cannot ``await`` the async :func:`record_usage`.
    This is the same best-effort upsert, run inline: a no-op for a disabled
    quota or a cookie caller (no I/O), and a logged-and-swallowed warning on any
    database error so a usage-write fault never breaks the in-flight stream.

    It opens its OWN short-lived ``app.db`` connection — never the request's —
    so a client disconnect that closes the request connection on the loop thread
    cannot race this write; the two touch different connections, exactly as the
    stream's recent-search write does.

    Args:
        api_key_id: The matched ``api_keys`` row id, or ``None`` for a cookie
            caller.
        quota: ``SEARCH_KEY_DAILY_TOKEN_QUOTA`` — ``0`` disables recording.
        tokens: The completed query's total LLM token count.
        app_db_path: Filesystem path to ``app.db``.
    """
    if not _is_quota_active(quota, api_key_id):
        return
    assert api_key_id is not None
    try:
        _write_usage(app_db_path, api_key_id, tokens)
    except Exception:
        # rationale: outer-boundary best-effort write (CODE_GUIDELINES §6.4) —
        # a usage-write failure must never break the already-streaming search.
        # log.exception attaches the traceback (§7.5); the soft cap tolerates a
        # lost record.
        log.exception("search.quota_record_failed", api_key_id=api_key_id)


def _read_tokens_used(app_db_path: str, api_key_id: int) -> int:
    """Open ``app.db``, read the key's tokens-used-today, close the connection.

    The blocking body :func:`check_quota` dispatches to the threadpool. A fresh
    per-call connection (never a shared one) keeps this safe alongside the
    request's own connection, matching the per-request connection model.
    """
    conn = connect(app_db_path)
    try:
        return key_usage.get_tokens_used(conn, api_key_id, key_usage.utc_today())
    finally:
        conn.close()


def _write_usage(app_db_path: str, api_key_id: int, tokens: int) -> None:
    """Open ``app.db``, add the query's tokens to today's bucket, close it.

    The blocking body :func:`record_usage` dispatches to the threadpool. Opens
    its own short-lived connection so a stream worker recording usage after the
    request connection has closed touches a different connection — race-free,
    exactly as the recent-search stream write does.
    """
    conn = connect(app_db_path)
    try:
        key_usage.add_usage(
            conn, api_key_id, key_usage.utc_today(), tokens=tokens, calls=1
        )
    finally:
        conn.close()
