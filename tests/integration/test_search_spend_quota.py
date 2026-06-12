"""Integration tests for the per-API-key daily LLM-token spend quota.

Exercises the full enforcement path through the real FastAPI app via TestClient.
The SearchCore is stubbed so no real LLM calls are made; a real migrated app.db
backs the quota read/write so the actual SQLite paths are exercised end-to-end.

Coverage:
1. DISABLED-DEFAULT (most important): SEARCH_KEY_DAILY_TOKEN_QUOTA=0 writes NO
   api_key_usage rows — the default deployment is completely unaffected.
2. ENFORCEMENT 429: an API-key caller's searches succeed until the daily token cap
   is reached, then /api/search returns HTTP 429 with a Retry-After header BEFORE
   the pipeline runs.
3. STREAM ENDPOINT 429: /api/search/stream enforces the same 429 rejection.
4. COOKIE CALLER NOT LIMITED: a browser/cookie caller is never rejected and never
   recorded, even with a positive quota.
5. RECORDING + PER-KEY ISOLATION: a completed search by key A adds tokens to key A's
   daily bucket; key B's bucket is unaffected.
6. 429 RESPONSE SHAPE: the response carries a Retry-After header and a structured
   JSON detail body.

Note on the MCP path: the MCP harness uses an in-process transport that does not
easily allow per-request bearer-token injection in the quota-relevant path (the
middleware sets the ContextVar, but the in-memory session does not drive the full
auth flow per tool call). The MCP quota enforcement is covered at the unit level in
tests/unit/search/test_spend_quota.py (check_quota / record_usage / mcp_api_key_id).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from appdb.connection import connect
from appdb.key_usage import add_usage, get_tokens_used, utc_today
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from appdb.passwords import hash_password
from search.sessions import begin_session
from search.appstate import AppState, attach_app_state
from search.auth import SESSION_COOKIE_NAME
from search.deps import get_current_user, require_role
from search.offload import LazySemaphore
from search.routes import build_api_router
from search.setup import SetupState
from tests.helpers.factories import (
    make_search_result,
    make_search_settings,
    make_search_stats,
    make_source_document,
)
from tests.helpers.search import mint_api_key


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_app(
    tmp_path: Path,
    *,
    core: MagicMock,
    quota: int,
) -> FastAPI:
    """Build a FastAPI app with the search router over a real tmp_path app.db.

    Mirrors the pattern in test_routes_record_search.py: mounts only the search
    router (no full create_app) so we can control every dependency precisely.
    The SEARCH_KEY_DAILY_TOKEN_QUOTA value is injected via the settings mock so
    the handler picks it up from core.settings, matching the production flow.
    """
    app_db_path = str(tmp_path / "app.db")
    settings = make_search_settings(
        APP_DB_PATH=app_db_path,
        SEARCH_KEY_DAILY_TOKEN_QUOTA=quota,
    )
    # The search handler reads quota from core.settings, so the core's settings
    # must carry the same quota value.
    core.settings = settings

    app = FastAPI()
    attach_app_state(
        app.state,
        AppState(
            app_db_path=app_db_path,
            setup_state=SetupState(),
        ),
    )
    app.include_router(
        build_api_router(
            settings,
            lambda _path: core,
            MagicMock(),
            require_reader=require_role("readonly"),
            require_member=require_role("member"),
            get_current_user=get_current_user,
            search_semaphore=LazySemaphore(4),
        )
    )
    return app


def _make_client(
    tmp_path: Path,
    *,
    core: MagicMock,
    quota: int = 0,
) -> TestClient:
    """Build a TestClient wrapping the search app."""
    app = _build_app(tmp_path, core=core, quota=quota)
    return TestClient(app, raise_server_exceptions=False, base_url="https://testserver")


def _ensure_app_db(tmp_path: Path) -> str:
    """Ensure the app.db is migrated and return its path."""
    path = str(tmp_path / "app.db")
    conn = connect(path)
    ensure_schema(conn)
    conn.close()
    return path


def _make_core(total_tokens: int = 500) -> MagicMock:
    """A stub SearchCore returning a fixed result with a controllable token total.

    *total_tokens* is the value the handler will record against the key's daily
    bucket — the mechanism the quota enforcement tests use to deterministically
    push a key's bucket over the cap.
    """
    core = MagicMock()
    core.answer.return_value = make_search_result(
        answer="The bill is £198.00.",
        sources=(
            make_source_document(
                document_id=100,
                title="BritishGas Invoice",
                correspondent="BritishGas",
                document_type="Invoice",
                created="2024-03-01T00:00:00Z",
                snippet="Your total bill amount is £198.00.",
                score=0.95,
            ),
        ),
        stats=make_search_stats(total_tokens=total_tokens),
    )
    # core.settings will be overridden by _build_app to carry the real quota.
    core.settings = make_search_settings()
    return core


def _seed_api_key(
    tmp_path: Path,
    *,
    username: str = "api-user",
    role: str = "readonly",
    scopes: str = "api",
) -> tuple[str, int]:
    """Create a user and an API key in app.db; return (raw_key, api_key_id).

    The id is needed to inspect the api_key_usage table directly.
    """
    path = str(tmp_path / "app.db")
    conn = connect(path)
    try:
        user = create_user(
            conn,
            username=username,
            password_hash=hash_password("pw"),
            role=role,
        )
        raw_key = mint_api_key(conn, owner_user_id=user.id, scopes=scopes)
        # Retrieve the key id (mint_api_key does not return it).
        row = conn.execute(
            "SELECT id FROM api_keys ORDER BY id DESC LIMIT 1"
        ).fetchone()
        key_id = row["id"]
    finally:
        conn.close()
    return raw_key, key_id


def _bearer(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def _usage_count(tmp_path: Path) -> int:
    """Return the total number of api_key_usage rows in app.db."""
    conn = connect(str(tmp_path / "app.db"))
    try:
        return conn.execute("SELECT COUNT(*) FROM api_key_usage").fetchone()[0]
    finally:
        conn.close()


def _tokens_used_today(tmp_path: Path, api_key_id: int) -> int:
    """Return the tokens recorded for *api_key_id* today in app.db."""
    conn = connect(str(tmp_path / "app.db"))
    try:
        return get_tokens_used(conn, api_key_id, utc_today())
    finally:
        conn.close()


def _seed_usage(tmp_path: Path, api_key_id: int, tokens: int) -> None:
    """Directly seed today's usage bucket, bypassing the quota module."""
    conn = connect(str(tmp_path / "app.db"))
    try:
        add_usage(conn, api_key_id, utc_today(), tokens=tokens, calls=1)
    finally:
        conn.close()


def _login_as_cookie_user(
    tmp_path: Path,
    client: TestClient,
    *,
    username: str = "browser-user",
    role: str = "readonly",
) -> None:
    """Create a user in app.db and set a session cookie on *client*."""
    path = str(tmp_path / "app.db")
    conn = connect(path)
    try:
        user = create_user(
            conn,
            username=username,
            password_hash=hash_password("pw"),
            role=role,
        )
        session = begin_session(conn, user_id=user.id, ttl_seconds=3600)
    finally:
        conn.close()
    client.cookies.set(SESSION_COOKIE_NAME, session.token)


# ---------------------------------------------------------------------------
# 1. DISABLED-DEFAULT ZERO-I/O
# ---------------------------------------------------------------------------


class TestDisabledQuotaZeroIO:
    """SEARCH_KEY_DAILY_TOKEN_QUOTA=0 (the default) must write NO api_key_usage rows."""

    def test_api_key_search_writes_no_usage_rows_when_quota_disabled(
        self, tmp_path: Path
    ) -> None:
        """A successful API-key search with quota=0 must leave api_key_usage empty.

        This is the behaviour-preserving guarantee: every deployment that has not
        opted in to a positive quota pays zero quota-related I/O on the search path.
        """
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=500)
        client = _make_client(tmp_path, core=core, quota=0)
        raw_key, _ = _seed_api_key(tmp_path)

        response = client.post(
            "/api/search",
            json={"query": "gas bill"},
            headers=_bearer(raw_key),
        )
        assert response.status_code == 200
        # The most important assertion: the table is completely empty.
        assert _usage_count(tmp_path) == 0, (
            "api_key_usage table must be empty when the quota is disabled (0); "
            "quota I/O is unconditionally skipped when SEARCH_KEY_DAILY_TOKEN_QUOTA=0"
        )

    def test_stream_search_writes_no_usage_rows_when_quota_disabled(
        self, tmp_path: Path
    ) -> None:
        """The streaming endpoint also writes no usage rows when quota=0."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=500)
        client = _make_client(tmp_path, core=core, quota=0)
        raw_key, _ = _seed_api_key(tmp_path)

        response = client.post(
            "/api/search/stream",
            json={"query": "gas bill"},
            headers=_bearer(raw_key),
        )
        assert response.status_code == 200
        assert _usage_count(tmp_path) == 0


# ---------------------------------------------------------------------------
# 2. ENFORCEMENT — 429 before the pipeline runs
# ---------------------------------------------------------------------------


class TestQuotaEnforcement429:
    """An over-quota API-key caller is rejected with HTTP 429 before the pipeline."""

    def test_search_succeeds_while_under_quota(self, tmp_path: Path) -> None:
        """A key whose tokens_used is below the cap must get HTTP 200."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=100)
        raw_key, key_id = _seed_api_key(tmp_path)
        # Pre-seed 400 tokens; quota is 500 — still under the cap.
        _seed_usage(tmp_path, key_id, tokens=400)
        client = _make_client(tmp_path, core=core, quota=500)

        response = client.post(
            "/api/search",
            json={"query": "gas bill"},
            headers=_bearer(raw_key),
        )
        assert response.status_code == 200

    def test_search_returns_429_when_quota_reached(self, tmp_path: Path) -> None:
        """An over-quota key is rejected before the pipeline runs."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=100)
        raw_key, key_id = _seed_api_key(tmp_path)
        # Pre-seed exactly the quota — tokens_used == quota triggers the 429.
        _seed_usage(tmp_path, key_id, tokens=500)
        client = _make_client(tmp_path, core=core, quota=500)

        response = client.post(
            "/api/search",
            json={"query": "gas bill"},
            headers=_bearer(raw_key),
        )
        assert response.status_code == 429
        # The pipeline must NOT have been called.
        core.answer.assert_not_called()

    def test_search_returns_429_after_crossing_quota_via_queries(
        self, tmp_path: Path
    ) -> None:
        """Successive real queries accumulate tokens until the cap is crossed.

        Quota is set just below two queries' combined token cost so the first
        succeeds (records 300 tokens → bucket at 300 < 400) and the second is
        rejected (bucket at 300 >= 400 — wait, that's still under; set quota
        exactly equal to one query's tokens so the second call is rejected).
        """
        _ensure_app_db(tmp_path)
        # Each query costs 400 tokens; quota is 400 — the first query fills the
        # bucket exactly, the second is rejected.
        token_cost = 400
        quota = 400
        core = _make_core(total_tokens=token_cost)
        raw_key, key_id = _seed_api_key(tmp_path)
        client = _make_client(tmp_path, core=core, quota=quota)

        # First query: bucket is empty → 0 < 400 → passes; records 400 tokens.
        r1 = client.post(
            "/api/search",
            json={"query": "first query"},
            headers=_bearer(raw_key),
        )
        assert r1.status_code == 200

        # Second query: bucket is at 400 == quota → rejected.
        r2 = client.post(
            "/api/search",
            json={"query": "second query"},
            headers=_bearer(raw_key),
        )
        assert r2.status_code == 429
        # The pipeline must have been called exactly once (for the first query only).
        assert core.answer.call_count == 1

    def test_stream_endpoint_returns_429_when_quota_reached(
        self, tmp_path: Path
    ) -> None:
        """The streaming endpoint enforces the same pre-pipeline 429 rejection."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=100)
        raw_key, key_id = _seed_api_key(tmp_path)
        _seed_usage(tmp_path, key_id, tokens=500)
        client = _make_client(tmp_path, core=core, quota=500)

        response = client.post(
            "/api/search/stream",
            json={"query": "gas bill"},
            headers=_bearer(raw_key),
        )
        assert response.status_code == 429
        core.answer.assert_not_called()


# ---------------------------------------------------------------------------
# 3. 429 RESPONSE SHAPE
# ---------------------------------------------------------------------------


class TestQuota429ResponseShape:
    """The 429 response must carry a Retry-After header and structured JSON detail."""

    def test_429_has_retry_after_header(self, tmp_path: Path) -> None:
        """The Retry-After header is present and is a positive integer (seconds)."""
        _ensure_app_db(tmp_path)
        core = _make_core()
        raw_key, key_id = _seed_api_key(tmp_path)
        _seed_usage(tmp_path, key_id, tokens=1000)
        client = _make_client(tmp_path, core=core, quota=500)

        response = client.post(
            "/api/search",
            json={"query": "over quota"},
            headers=_bearer(raw_key),
        )
        assert response.status_code == 429
        assert "retry-after" in response.headers, (
            "HTTP 429 must carry a Retry-After header pointing at the next UTC midnight"
        )
        retry_after = int(response.headers["retry-after"])
        assert retry_after >= 1, "Retry-After must be at least 1 second"
        # At most 86400 seconds (one full day) away.
        assert retry_after <= 86400

    def test_429_body_contains_detail(self, tmp_path: Path) -> None:
        """The 429 body is JSON with a 'detail' field naming the quota."""
        _ensure_app_db(tmp_path)
        core = _make_core()
        raw_key, key_id = _seed_api_key(tmp_path)
        _seed_usage(tmp_path, key_id, tokens=1000)
        client = _make_client(tmp_path, core=core, quota=500)

        response = client.post(
            "/api/search",
            json={"query": "over quota"},
            headers=_bearer(raw_key),
        )
        assert response.status_code == 429
        body = response.json()
        assert "detail" in body
        # The detail mentions the quota or the word "quota" to be client-readable.
        assert "quota" in body["detail"].lower() or "token" in body["detail"].lower()


# ---------------------------------------------------------------------------
# 4. COOKIE CALLER NOT LIMITED
# ---------------------------------------------------------------------------


class TestCookieCallerNotLimited:
    """A browser/cookie caller is never rejected and never recorded."""

    def test_cookie_caller_always_succeeds_with_positive_quota(
        self, tmp_path: Path
    ) -> None:
        """A cookie user is never 429'd regardless of quota setting."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=99999)
        client = _make_client(tmp_path, core=core, quota=1)
        _login_as_cookie_user(tmp_path, client)

        response = client.post("/api/search", json={"query": "gas bill"})
        assert response.status_code == 200

    def test_cookie_caller_writes_no_usage_row(self, tmp_path: Path) -> None:
        """A cookie user's successful search writes nothing to api_key_usage."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=500)
        client = _make_client(tmp_path, core=core, quota=1000)
        _login_as_cookie_user(tmp_path, client)

        response = client.post("/api/search", json={"query": "gas bill"})
        assert response.status_code == 200
        assert _usage_count(tmp_path) == 0

    def test_cookie_caller_on_stream_writes_no_usage_row(self, tmp_path: Path) -> None:
        """A cookie user's streaming search also writes nothing to api_key_usage."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=500)
        client = _make_client(tmp_path, core=core, quota=1000)
        _login_as_cookie_user(tmp_path, client)

        response = client.post("/api/search/stream", json={"query": "gas bill"})
        assert response.status_code == 200
        assert _usage_count(tmp_path) == 0


# ---------------------------------------------------------------------------
# 5. RECORDING + PER-KEY ISOLATION
# ---------------------------------------------------------------------------


class TestRecordingAndPerKeyIsolation:
    """A completed search records tokens to the caller's bucket only."""

    def test_search_records_tokens_to_key_bucket(self, tmp_path: Path) -> None:
        """A successful API-key search records the query's token total."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=350)
        raw_key, key_id = _seed_api_key(tmp_path)
        client = _make_client(tmp_path, core=core, quota=10000)

        response = client.post(
            "/api/search",
            json={"query": "gas bill"},
            headers=_bearer(raw_key),
        )
        assert response.status_code == 200
        assert _tokens_used_today(tmp_path, key_id) == 350

    def test_key_a_record_does_not_affect_key_b_bucket(self, tmp_path: Path) -> None:
        """Recording tokens for key A leaves key B's bucket at zero."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=300)
        raw_key_a, key_id_a = _seed_api_key(tmp_path, username="user-a", scopes="api")
        raw_key_b, key_id_b = _seed_api_key(tmp_path, username="user-b", scopes="api")
        client = _make_client(tmp_path, core=core, quota=10000)

        # Only key A runs a query.
        response = client.post(
            "/api/search",
            json={"query": "gas bill"},
            headers=_bearer(raw_key_a),
        )
        assert response.status_code == 200
        assert _tokens_used_today(tmp_path, key_id_a) == 300
        assert _tokens_used_today(tmp_path, key_id_b) == 0

    def test_multiple_queries_accumulate_tokens_in_same_bucket(
        self, tmp_path: Path
    ) -> None:
        """Two queries by the same key add their tokens into one daily bucket."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=200)
        raw_key, key_id = _seed_api_key(tmp_path)
        client = _make_client(tmp_path, core=core, quota=10000)

        for query in ("first", "second"):
            r = client.post(
                "/api/search",
                json={"query": query},
                headers=_bearer(raw_key),
            )
            assert r.status_code == 200

        # 200 + 200 = 400 in a single row.
        assert _tokens_used_today(tmp_path, key_id) == 400
        assert _usage_count(tmp_path) == 1

    def test_stream_search_records_tokens(self, tmp_path: Path) -> None:
        """The streaming endpoint also records tokens to the key's daily bucket."""
        _ensure_app_db(tmp_path)
        core = _make_core(total_tokens=175)
        raw_key, key_id = _seed_api_key(tmp_path)
        client = _make_client(tmp_path, core=core, quota=10000)

        response = client.post(
            "/api/search/stream",
            json={"query": "gas bill"},
            headers=_bearer(raw_key),
        )
        assert response.status_code == 200
        # Give the worker thread time to complete the best-effort write (it runs
        # after the stream closes, so we just need to wait for the response body).
        assert _tokens_used_today(tmp_path, key_id) == 175
