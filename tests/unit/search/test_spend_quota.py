"""Unit tests for search.spend_quota — per-API-key daily LLM-token quota logic.

Tests the pure predicate and the async check_quota / record_usage / record_usage_blocking
functions directly, without routing or a real HTTP server. A real migrated app.db is used
so the actual SQLite read/write paths are exercised, but no LLM calls are made.

Coverage:
- _is_quota_active is False when quota=0 (disabled) or api_key_id=None (cookie caller).
- _is_quota_active is True only when both are set.
- check_quota does no I/O when quota is disabled (0).
- check_quota does no I/O when the caller is a cookie caller (api_key_id=None).
- check_quota passes when tokens_used < quota.
- check_quota raises QuotaExceededError when tokens_used >= quota.
- QuotaExceededError carries the correct quota and tokens_used attributes.
- record_usage does no I/O when quota is disabled.
- record_usage does no I/O for a cookie caller (api_key_id=None).
- record_usage writes to the daily bucket for a real API key under a positive quota.
- record_usage_blocking mirrors record_usage (same no-op gates, same write path).
- mcp_api_key_id ContextVar defaults to None and is readable/settable.
- UTC-day bucket isolation: tokens from yesterday are separate from today's bucket.
"""

from __future__ import annotations

import pytest

from appdb.connection import connect
from appdb.key_usage import add_usage, get_tokens_used, utc_today
from appdb.schema import ensure_schema
from search.spend_quota import (
    QuotaExceededError,
    _is_quota_active,
    check_quota,
    mcp_api_key_id,
    record_usage,
    record_usage_blocking,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_db_path(tmp_path) -> str:
    """A migrated app.db with one user and two API keys (ids 7 and 8).

    The foreign key is enforced, so usage rows must reference an existing api_keys row.
    Returns the path so the spend_quota functions can open their own connections,
    mirroring the production pattern (never sharing a connection across callers).
    """
    path = str(tmp_path / "app.db")
    conn = connect(path)
    ensure_schema(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, created_at, updated_at) "
        "VALUES (1, 'u', 'h', 'member', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO api_keys (id, key_hash, key_prefix, name, owner_user_id, scopes, created_at) "
        "VALUES (7, 'hash7', 'sk-pls-7', 'k7', 1, 'api', 'now')"
    )
    conn.execute(
        "INSERT INTO api_keys (id, key_hash, key_prefix, name, owner_user_id, scopes, created_at) "
        "VALUES (8, 'hash8', 'sk-pls-8', 'k8', 1, 'api', 'now')"
    )
    conn.commit()
    conn.close()
    return path


def _row_count(app_db_path: str) -> int:
    """Return the total number of api_key_usage rows."""
    conn = connect(app_db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM api_key_usage").fetchone()[0]
    finally:
        conn.close()


def _tokens_for(app_db_path: str, api_key_id: int, date: str) -> int:
    conn = connect(app_db_path)
    try:
        return get_tokens_used(conn, api_key_id, date)
    finally:
        conn.close()


def _seed_usage(
    app_db_path: str, api_key_id: int, tokens: int, date: str | None = None
) -> None:
    """Directly seed a daily usage bucket, bypassing the quota module."""
    conn = connect(app_db_path)
    try:
        add_usage(conn, api_key_id, date or utc_today(), tokens=tokens, calls=1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# _is_quota_active — pure predicate
# ---------------------------------------------------------------------------


class TestIsQuotaActive:
    """The predicate that gates all I/O in both steps."""

    def test_disabled_quota_is_not_active_regardless_of_key(self) -> None:
        """quota=0 means the cap is off; no key is ever limited."""
        assert _is_quota_active(0, api_key_id=42) is False

    def test_negative_quota_is_not_active(self) -> None:
        """A negative quota is treated as disabled — only strictly positive values enable it."""
        assert _is_quota_active(-1, api_key_id=42) is False

    def test_cookie_caller_is_not_active_even_with_positive_quota(self) -> None:
        """api_key_id=None (cookie/browser caller) is never rate-limited."""
        assert _is_quota_active(1000, api_key_id=None) is False

    def test_positive_quota_and_key_id_is_active(self) -> None:
        """Both conditions met: the quota check must run."""
        assert _is_quota_active(500, api_key_id=7) is True

    def test_quota_of_one_is_active_with_a_key(self) -> None:
        """Even a quota of 1 enables the cap for an API-key caller."""
        assert _is_quota_active(1, api_key_id=7) is True


# ---------------------------------------------------------------------------
# check_quota — pre-pipeline gate
# ---------------------------------------------------------------------------


class TestCheckQuota:
    """check_quota must short-circuit cleanly or raise QuotaExceededError."""

    @pytest.mark.anyio
    async def test_disabled_quota_does_no_io(self, app_db_path: str) -> None:
        """quota=0 returns immediately with zero database access."""
        # With no rows in the db and quota=0 this must succeed silently.
        await check_quota(api_key_id=7, quota=0, app_db_path=app_db_path)
        # No usage rows must have been written.
        assert _row_count(app_db_path) == 0

    @pytest.mark.anyio
    async def test_cookie_caller_does_no_io(self, app_db_path: str) -> None:
        """api_key_id=None (cookie caller) never touches the database."""
        await check_quota(api_key_id=None, quota=1000, app_db_path=app_db_path)
        assert _row_count(app_db_path) == 0

    @pytest.mark.anyio
    async def test_passes_when_bucket_is_empty(self, app_db_path: str) -> None:
        """An API key with no usage row today passes the check (0 < quota)."""
        # Should not raise.
        await check_quota(api_key_id=7, quota=1000, app_db_path=app_db_path)

    @pytest.mark.anyio
    async def test_passes_when_tokens_used_is_below_quota(
        self, app_db_path: str
    ) -> None:
        """tokens_used < quota must not raise."""
        _seed_usage(app_db_path, 7, tokens=499)
        await check_quota(api_key_id=7, quota=500, app_db_path=app_db_path)

    @pytest.mark.anyio
    async def test_raises_when_tokens_used_equals_quota(self, app_db_path: str) -> None:
        """tokens_used == quota is at the cap — must raise QuotaExceededError."""
        _seed_usage(app_db_path, 7, tokens=500)
        with pytest.raises(QuotaExceededError) as exc_info:
            await check_quota(api_key_id=7, quota=500, app_db_path=app_db_path)
        assert exc_info.value.quota == 500
        assert exc_info.value.tokens_used == 500

    @pytest.mark.anyio
    async def test_raises_when_tokens_used_exceeds_quota(
        self, app_db_path: str
    ) -> None:
        """tokens_used > quota (soft-cap overshoot) also raises."""
        _seed_usage(app_db_path, 7, tokens=600)
        with pytest.raises(QuotaExceededError) as exc_info:
            await check_quota(api_key_id=7, quota=500, app_db_path=app_db_path)
        assert exc_info.value.quota == 500
        assert exc_info.value.tokens_used == 600

    @pytest.mark.anyio
    async def test_error_carries_quota_and_tokens_used(self, app_db_path: str) -> None:
        """QuotaExceededError attributes are populated from the live values."""
        _seed_usage(app_db_path, 7, tokens=123)
        with pytest.raises(QuotaExceededError) as exc_info:
            await check_quota(api_key_id=7, quota=100, app_db_path=app_db_path)
        err = exc_info.value
        assert err.quota == 100
        assert err.tokens_used == 123

    @pytest.mark.anyio
    async def test_per_key_check_does_not_confuse_keys(self, app_db_path: str) -> None:
        """The check reads only the requesting key's bucket, not all keys'."""
        # Key 8 is over quota; key 7 is not.
        _seed_usage(app_db_path, 8, tokens=600)
        # Key 7 check must pass despite key 8 being over quota.
        await check_quota(api_key_id=7, quota=500, app_db_path=app_db_path)

    @pytest.mark.anyio
    async def test_yesterday_bucket_does_not_affect_today(
        self, app_db_path: str
    ) -> None:
        """Usage from a previous UTC day does not count toward today's quota."""
        conn = connect(app_db_path)
        try:
            add_usage(conn, 7, "2000-01-01", tokens=9999, calls=1)
        finally:
            conn.close()
        # Today's bucket is empty — should pass.
        await check_quota(api_key_id=7, quota=100, app_db_path=app_db_path)


# ---------------------------------------------------------------------------
# record_usage — post-pipeline write
# ---------------------------------------------------------------------------


class TestRecordUsage:
    """record_usage must write only when quota is active, and must swallow errors."""

    @pytest.mark.anyio
    async def test_disabled_quota_writes_nothing(self, app_db_path: str) -> None:
        """quota=0: the call completes without touching the database."""
        await record_usage(api_key_id=7, quota=0, tokens=500, app_db_path=app_db_path)
        assert _row_count(app_db_path) == 0

    @pytest.mark.anyio
    async def test_cookie_caller_writes_nothing(self, app_db_path: str) -> None:
        """api_key_id=None: the write is skipped regardless of quota."""
        await record_usage(
            api_key_id=None, quota=1000, tokens=500, app_db_path=app_db_path
        )
        assert _row_count(app_db_path) == 0

    @pytest.mark.anyio
    async def test_writes_tokens_to_daily_bucket(self, app_db_path: str) -> None:
        """A real API-key caller under a positive quota writes to today's bucket."""
        await record_usage(
            api_key_id=7, quota=1000, tokens=300, app_db_path=app_db_path
        )
        assert _tokens_for(app_db_path, 7, utc_today()) == 300

    @pytest.mark.anyio
    async def test_second_write_accumulates_in_place(self, app_db_path: str) -> None:
        """Two sequential record_usage calls add their tokens, not stack rows."""
        await record_usage(
            api_key_id=7, quota=1000, tokens=200, app_db_path=app_db_path
        )
        await record_usage(
            api_key_id=7, quota=1000, tokens=150, app_db_path=app_db_path
        )
        assert _tokens_for(app_db_path, 7, utc_today()) == 350
        # Still exactly one row.
        assert _row_count(app_db_path) == 1

    @pytest.mark.anyio
    async def test_write_is_per_key(self, app_db_path: str) -> None:
        """Writing for key 7 does not affect key 8's bucket."""
        await record_usage(
            api_key_id=7, quota=1000, tokens=400, app_db_path=app_db_path
        )
        assert _tokens_for(app_db_path, 8, utc_today()) == 0

    @pytest.mark.anyio
    async def test_db_error_is_swallowed_not_raised(
        self, app_db_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A database error while recording is logged and swallowed — not re-raised.

        record_usage is best-effort: a write fault must never fail an already-successful
        search. The quota is soft; a dropped record is acceptable.
        """
        import search.spend_quota as _module

        def _boom(*args, **kwargs) -> None:
            raise RuntimeError("db exploded")

        monkeypatch.setattr(_module, "_write_usage", _boom)
        # Must not raise.
        await record_usage(
            api_key_id=7, quota=1000, tokens=100, app_db_path=app_db_path
        )


# ---------------------------------------------------------------------------
# record_usage_blocking — sync variant used by the streaming worker
# ---------------------------------------------------------------------------


class TestRecordUsageBlocking:
    """Mirrors the async variant; same no-op gates and best-effort write."""

    def test_disabled_quota_writes_nothing(self, app_db_path: str) -> None:
        """quota=0: the blocking write is skipped."""
        record_usage_blocking(
            api_key_id=7, quota=0, tokens=500, app_db_path=app_db_path
        )
        assert _row_count(app_db_path) == 0

    def test_cookie_caller_writes_nothing(self, app_db_path: str) -> None:
        """api_key_id=None: the blocking write is skipped."""
        record_usage_blocking(
            api_key_id=None, quota=1000, tokens=500, app_db_path=app_db_path
        )
        assert _row_count(app_db_path) == 0

    def test_writes_tokens_to_daily_bucket(self, app_db_path: str) -> None:
        """A real API-key caller writes to today's bucket synchronously."""
        record_usage_blocking(
            api_key_id=7, quota=1000, tokens=250, app_db_path=app_db_path
        )
        assert _tokens_for(app_db_path, 7, utc_today()) == 250

    def test_db_error_is_swallowed_not_raised(
        self, app_db_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A database error while blocking-recording is swallowed, not re-raised."""
        import search.spend_quota as _module

        def _boom(*args, **kwargs) -> None:
            raise RuntimeError("db exploded")

        monkeypatch.setattr(_module, "_write_usage", _boom)
        record_usage_blocking(
            api_key_id=7, quota=1000, tokens=100, app_db_path=app_db_path
        )


# ---------------------------------------------------------------------------
# mcp_api_key_id ContextVar
# ---------------------------------------------------------------------------


class TestMcpApiKeyIdContextVar:
    """The ContextVar that carries the key id from MCP auth middleware to tool handlers."""

    def test_default_is_none(self) -> None:
        """The default value is None, meaning 'not an API-key caller'."""
        assert mcp_api_key_id.get() is None

    def test_can_be_set_and_reset(self) -> None:
        """The ContextVar can be set to a key id and reset back to None."""
        token = mcp_api_key_id.set(42)
        assert mcp_api_key_id.get() == 42
        mcp_api_key_id.reset(token)
        assert mcp_api_key_id.get() is None


# ---------------------------------------------------------------------------
# UTC-day isolation — bucket keyed on the calendar date
# ---------------------------------------------------------------------------


class TestUtcDayIsolation:
    """Quota buckets are keyed on the UTC calendar date; a new day starts fresh."""

    @pytest.mark.anyio
    async def test_yesterday_tokens_do_not_count_towards_today(
        self, app_db_path: str
    ) -> None:
        """Pre-seeding yesterday's bucket leaves today's check clean."""
        yesterday = "2000-06-11"
        conn = connect(app_db_path)
        try:
            add_usage(conn, 7, yesterday, tokens=9999, calls=10)
        finally:
            conn.close()
        # Today's bucket is empty — check passes and record creates a new row.
        await check_quota(api_key_id=7, quota=100, app_db_path=app_db_path)
        await record_usage(api_key_id=7, quota=100, tokens=50, app_db_path=app_db_path)
        # Yesterday's total is unchanged.
        assert _tokens_for(app_db_path, 7, yesterday) == 9999
        # Today's total is only the newly recorded tokens.
        assert _tokens_for(app_db_path, 7, utc_today()) == 50
