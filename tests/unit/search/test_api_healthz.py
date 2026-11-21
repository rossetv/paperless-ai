"""Tests for the search server's healthz endpoint and concurrency cap."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from search.routes import evaluate_index_health
from store import SchemaNotReadyError, StoreError
from tests.helpers.factories import (
    make_index_stats,
    make_search_result,
    make_search_settings,
)
from tests.helpers.search import mint_api_key
from tests.unit.search.conftest import build_test_client


def _settings(db_path: str, **overrides: object) -> MagicMock:
    """Build a Settings-like mock pointing at *db_path*."""
    return make_search_settings(INDEX_DB_PATH=db_path, **overrides)


def _seed_api_key(settings: MagicMock) -> str:
    """Seed a user and an API key in the app.db; return the raw key string."""
    from appdb.connection import connect
    from appdb.passwords import hash_password
    from appdb.users import create as create_user

    conn = connect(settings.APP_DB_PATH)
    try:
        user = create_user(
            conn,
            username="api-user",
            password_hash=hash_password("pw"),
            role="member",
        )
        return mint_api_key(conn, owner_user_id=user.id, scopes="api")
    finally:
        conn.close()


def _bearer_headers(raw_key: str) -> dict[str, str]:
    """Return an Authorization header carrying *raw_key* as a Bearer token."""
    return {"Authorization": f"Bearer {raw_key}"}


class TestEvaluateIndexHealth:
    """The three-state index-health evaluation, exercised in isolation."""

    def test_ok_when_reconciled_and_quick_check_passes(self) -> None:
        store_reader = MagicMock()
        store_reader.get_stats.return_value = make_index_stats(
            last_reconcile_at="2024-06-01T12:00:00Z"
        )
        store_reader.quick_check.return_value = True

        assert evaluate_index_health(store_reader).state == "ok"

    def test_not_ready_when_schema_missing(self) -> None:
        """A SchemaNotReadyError from get_stats maps to index-not-ready."""
        store_reader = MagicMock()
        store_reader.get_stats.side_effect = SchemaNotReadyError(
            "the index schema is not present"
        )

        health = evaluate_index_health(store_reader)
        assert health.state == "index-not-ready"
        assert health.reason == "schema_missing"

    def test_not_ready_when_get_stats_fails_unexpectedly(self) -> None:
        """A generic StoreError from get_stats maps to index-not-ready."""
        store_reader = MagicMock()
        store_reader.get_stats.side_effect = StoreError("disk I/O error")

        assert evaluate_index_health(store_reader).state == "index-not-ready"

    def test_not_ready_when_never_reconciled(self) -> None:
        store_reader = MagicMock()
        store_reader.get_stats.return_value = make_index_stats(last_reconcile_at=None)

        health = evaluate_index_health(store_reader)
        assert health.state == "index-not-ready"
        assert health.reason == "never_reconciled"

    def test_corrupt_when_quick_check_fails(self) -> None:
        store_reader = MagicMock()
        store_reader.get_stats.return_value = make_index_stats(
            last_reconcile_at="2024-06-01T12:00:00Z"
        )
        store_reader.quick_check.return_value = False

        assert evaluate_index_health(store_reader).state == "index-corrupt"


def test_healthz_returns_503_when_db_absent() -> None:
    """GET /api/healthz returns 503 index-not-ready when the DB does not exist."""
    client = build_test_client(
        _settings("/nonexistent/index.db"), store_reader=MagicMock()
    )
    response = client.get("/api/healthz")
    assert response.status_code == 503
    assert response.json().get("status") == "index-not-ready"


def test_healthz_returns_503_when_db_present_but_schema_missing(
    tmp_path: Path,
) -> None:
    """GET /api/healthz returns 503 index-not-ready when the DB has no schema.

    sqlite3.connect creates an empty file when the directory is writable, so a
    present-but-empty file does not mean the index is ready.
    """
    db_path = tmp_path / "index.db"
    db_path.write_bytes(b"")  # Empty file — no schema written yet.
    store_reader = MagicMock()
    store_reader.get_stats.side_effect = SchemaNotReadyError(
        "get_stats query failed: the index schema is not present"
    )
    client = build_test_client(_settings(str(db_path)), store_reader=store_reader)

    response = client.get("/api/healthz")
    assert response.status_code == 503
    assert response.json().get("status") == "index-not-ready"


def test_healthz_returns_503_when_schema_present_but_never_reconciled(
    tmp_path: Path,
) -> None:
    """GET /api/healthz returns 503 index-not-ready when the index was never reconciled.

    A DB with the schema created but last_reconcile_at=None means the indexer
    ran ensure_schema but has not completed its first cycle.
    """
    db_path = tmp_path / "index.db"
    db_path.write_bytes(b"")
    store_reader = MagicMock()
    store_reader.get_stats.return_value = make_index_stats(last_reconcile_at=None)
    client = build_test_client(_settings(str(db_path)), store_reader=store_reader)

    response = client.get("/api/healthz")
    assert response.status_code == 503
    assert response.json().get("status") == "index-not-ready"


def test_healthz_returns_503_when_index_corrupt(tmp_path: Path) -> None:
    """GET /api/healthz returns 503 index-corrupt when quick_check fails.

    The DB needs a schema and a reconcile timestamp for the corruption check to run.
    """
    db_path = tmp_path / "index.db"
    db_path.write_bytes(b"")
    store_reader = MagicMock()
    store_reader.get_stats.return_value = make_index_stats(
        document_count=10,
        chunk_count=50,
        last_reconcile_at="2024-06-01T12:00:00Z",
    )
    store_reader.quick_check.return_value = False
    client = build_test_client(_settings(str(db_path)), store_reader=store_reader)

    response = client.get("/api/healthz")
    assert response.status_code == 503
    assert response.json().get("status") == "index-corrupt"


def test_healthz_returns_200_when_healthy(tmp_path: Path) -> None:
    """GET /api/healthz returns 200 when the index is populated, reconciled, healthy."""
    db_path = tmp_path / "index.db"
    db_path.write_bytes(b"")
    store_reader = MagicMock()
    store_reader.get_stats.return_value = make_index_stats(
        document_count=5,
        chunk_count=20,
        last_reconcile_at="2024-06-01T12:00:00Z",
    )
    store_reader.quick_check.return_value = True
    client = build_test_client(_settings(str(db_path)), store_reader=store_reader)

    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json().get("status") == "ok"


def test_healthz_does_not_require_auth() -> None:
    """GET /api/healthz must be accessible without authentication."""
    client = build_test_client(_settings("/nonexistent/index.db"))
    assert client.get("/api/healthz").status_code != 401


def test_search_max_concurrent_semaphore_is_created_and_limits_search() -> None:
    """SEARCH_MAX_CONCURRENT creates an asyncio.Semaphore that caps /api/search.

    Only checks that sequential requests within the limit succeed; the async test
    below exercises real concurrency.
    """
    core = MagicMock()
    core.answer.return_value = make_search_result()
    settings = _settings("/nonexistent/index.db", SEARCH_MAX_CONCURRENT=2)
    client = build_test_client(settings, core=core)
    raw_key = _seed_api_key(settings)

    for _ in range(3):
        response = client.post(
            "/api/search", json={"query": "test"}, headers=_bearer_headers(raw_key)
        )
        assert response.status_code == 200


@pytest.mark.anyio
async def test_semaphore_caps_concurrent_requests_to_max_concurrent() -> None:
    """The asyncio.Semaphore genuinely limits concurrent in-flight requests.

    Fires ``SEARCH_MAX_CONCURRENT + 1`` concurrent requests and asserts no more than
    ``SEARCH_MAX_CONCURRENT`` are inside ``core.answer`` at once. One
    ``httpx.AsyncClient`` keeps them on one event loop, so they share one semaphore.
    """
    import asyncio

    import httpx

    from search.api import create_app

    max_concurrent = 2
    settings = _settings("/nonexistent/index.db", SEARCH_MAX_CONCURRENT=max_concurrent)

    # Shared mutable state across executor threads.
    inside_counter = 0
    peak_inside = 0
    counter_lock = threading.Lock()
    block_event = threading.Event()
    blocked_count = 0
    blocked_enough = threading.Event()

    def blocking_answer(**_kwargs: Any) -> Any:
        nonlocal inside_counter, peak_inside, blocked_count
        with counter_lock:
            inside_counter += 1
            blocked_count += 1
            if inside_counter > peak_inside:
                peak_inside = inside_counter
            if blocked_count >= max_concurrent:
                blocked_enough.set()
        block_event.wait(timeout=5.0)
        with counter_lock:
            inside_counter -= 1
        return make_search_result()

    core = MagicMock()
    core.answer.side_effect = blocking_answer
    core.settings = settings

    store_reader = MagicMock()
    store_reader.list_facets.return_value = None
    store_reader.get_stats.return_value = None
    store_reader.quick_check.return_value = True
    app = create_app(settings, core=core, store_reader=store_reader)
    raw_key = _seed_api_key(settings)

    total_requests = max_concurrent + 1

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as aclient:
        tasks = [
            asyncio.create_task(
                aclient.post(
                    "/api/search",
                    json={"query": "test"},
                    headers=_bearer_headers(raw_key),
                )
            )
            for _ in range(total_requests)
        ]

        # Wait until max_concurrent executor threads are inside core.answer,
        # confirming the semaphore is holding one request back.
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: blocked_enough.wait(timeout=5.0))

        with counter_lock:
            observed_peak = peak_inside

        assert observed_peak <= max_concurrent, (
            f"Semaphore breached: {observed_peak} concurrent calls inside "
            f"core.answer, limit is {max_concurrent}"
        )

        block_event.set()
        responses = await asyncio.gather(*tasks)

    statuses = [r.status_code for r in responses]
    assert all(s == 200 for s in statuses), f"Some requests failed: {statuses}"
