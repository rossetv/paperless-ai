"""The per-key daily token quota on the MCP tools.

Only ``deep_search`` is gated and counted; the other tools are free. Runs
against a real migrated app.db through the in-memory MCP transport.
"""

from __future__ import annotations

import asyncio
import gc
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anyio
import pytest
import structlog.testing

from appdb.connection import connect
from appdb.key_usage import add_usage, get_tokens_used, utc_today
from appdb.schema import ensure_schema
from search import mcp_server
from search.mcp_server import build_mcp_app
from search.offload import LazySemaphore
from search.spend_quota import mcp_api_key_id
from tests.helpers.factories import (
    make_facet_set,
    make_search_result,
    make_search_settings,
    make_search_stats,
)
from tests.helpers.llm import (
    ScriptedLLMClient,
    answered_response_json,
    planner_response_json,
)
from tests.helpers.search import build_search_core

QUOTA = 100


@pytest.fixture()
def app_db_path(tmp_path) -> str:
    """A migrated app.db with one user and one API key (id 7)."""
    path = str(tmp_path / "app.db")
    conn = connect(path)
    ensure_schema(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, created_at, updated_at) "
        "VALUES (1, 'u', 'h', 'member', 'now', 'now')"
    )
    conn.execute(
        "INSERT INTO api_keys (id, key_hash, key_prefix, name, owner_user_id, scopes, created_at) "
        "VALUES (7, 'hash7', 'sk-pls-7', 'k7', 1, 'mcp', 'now')"
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture(autouse=True)
def _as_api_key_7():
    token = mcp_api_key_id.set(7)
    yield
    mcp_api_key_id.reset(token)


def _tokens_used(app_db_path: str) -> int:
    conn = connect(app_db_path)
    try:
        return get_tokens_used(conn, 7, utc_today())
    finally:
        conn.close()


def _use_up_quota(app_db_path: str) -> None:
    conn = connect(app_db_path)
    try:
        add_usage(conn, 7, utc_today(), tokens=QUOTA, calls=1)
    finally:
        conn.close()


def _make_core(*, max_concurrent: int = 4, answer_tokens: int = 50) -> MagicMock:
    core = MagicMock()
    core.settings = make_search_settings(
        SEARCH_KEY_DAILY_TOKEN_QUOTA=QUOTA, SEARCH_MAX_CONCURRENT=max_concurrent
    )
    stats = make_search_stats(total_tokens=answer_tokens)
    core.answer.return_value = make_search_result(stats=stats)
    core.retrieve.return_value = make_search_result(stats=stats)
    return core


def _build(core: MagicMock, app_db_path: str):
    return build_mcp_app(
        lambda _path: core,
        app_db_path,
        search_semaphore=LazySemaphore(core.settings.SEARCH_MAX_CONCURRENT),
    )


def _text(result) -> str:
    return " ".join(b.text for b in result.content if hasattr(b, "text"))


@pytest.mark.anyio
async def test_semantic_search_still_runs_after_the_quota_is_used_up(
    app_db_path: str,
) -> None:
    from tests.helpers.mcp_client import connect_client

    _use_up_quota(app_db_path)
    core = _make_core()
    app = _build(core, app_db_path)

    async with connect_client(app._server) as client:
        result = await client.call_tool("semantic_search", {"query": "invoice"})

    assert result.isError is False
    core.retrieve.assert_called_once()


@pytest.mark.anyio
async def test_semantic_search_does_not_count_against_the_quota(
    app_db_path: str,
) -> None:
    from tests.helpers.mcp_client import connect_client

    core = _make_core()
    app = _build(core, app_db_path)

    async with connect_client(app._server) as client:
        await client.call_tool("semantic_search", {"query": "invoice"})

    assert _tokens_used(app_db_path) == 0


@pytest.mark.anyio
async def test_deep_search_is_counted_and_then_refused_at_the_quota(
    app_db_path: str,
) -> None:
    from tests.helpers.mcp_client import connect_client

    core = _make_core(answer_tokens=QUOTA)
    app = _build(core, app_db_path)

    async with connect_client(app._server) as client:
        first = await client.call_tool("deep_search", {"question": "invoice"})
        second = await client.call_tool("deep_search", {"question": "invoice"})

    assert first.isError is False
    assert _tokens_used(app_db_path) == QUOTA
    assert second.isError is True
    assert "quota" in _text(second).lower()
    core.answer.assert_called_once()


@pytest.mark.anyio
async def test_deep_search_answered_from_the_cache_records_no_tokens(
    app_db_path: str,
) -> None:
    from tests.helpers.mcp_client import connect_client

    core = _make_core(answer_tokens=50)

    def _cached_answer(*, on_cache_hit=None, **_kwargs):
        on_cache_hit()
        return core.answer.return_value

    core.answer.side_effect = _cached_answer
    app = _build(core, app_db_path)

    async with connect_client(app._server) as client:
        result = await client.call_tool("deep_search", {"question": "invoice"})

    assert result.isError is False
    assert _tokens_used(app_db_path) == 0


@pytest.mark.anyio
async def test_deep_search_waiting_for_a_slot_is_refused_if_the_quota_ran_out_meanwhile(
    app_db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.helpers.mcp_client import connect_client

    core = _make_core(max_concurrent=1, answer_tokens=QUOTA)
    in_answer = threading.Event()
    release = threading.Event()

    def _blocking_answer(**_kwargs):
        in_answer.set()
        release.wait(timeout=5)
        return make_search_result(stats=make_search_stats(total_tokens=QUOTA))

    core.answer.side_effect = _blocking_answer

    checks = 0
    all_checks_seen = {}
    real_check = mcp_server.check_quota

    async def _counting_check(**kwargs):
        nonlocal checks
        await real_check(**kwargs)
        checks += 1
        if checks in all_checks_seen:
            all_checks_seen[checks].set()

    monkeypatch.setattr(mcp_server, "check_quota", _counting_check)

    app = _build(core, app_db_path)
    results = {}

    async def _call(name: str, client) -> None:
        results[name] = await client.call_tool("deep_search", {"question": "q"})

    async with connect_client(app._server) as client:
        async with anyio.create_task_group() as tg:
            # The first call passes both checks and holds the only slot.
            tg.start_soon(_call, "first", client)
            await anyio.to_thread.run_sync(in_answer.wait)
            first_call_checks = checks
            # The second passes its early check, then waits for the slot.
            all_checks_seen[first_call_checks + 1] = anyio.Event()
            tg.start_soon(_call, "second", client)
            with anyio.fail_after(5):
                await all_checks_seen[first_call_checks + 1].wait()
            release.set()

    assert results["first"].isError is False
    assert results["second"].isError is True
    assert "quota" in _text(results["second"]).lower()
    core.answer.assert_called_once()


@pytest.mark.anyio
async def test_cancelled_deep_search_keeps_its_slot_until_the_work_ends_and_records_its_tokens(
    app_db_path: str,
) -> None:
    core = _make_core(max_concurrent=1, answer_tokens=40)
    in_answer = threading.Event()
    release = threading.Event()

    def _blocking_answer(**_kwargs):
        in_answer.set()
        release.wait(timeout=5)
        return make_search_result(stats=make_search_stats(total_tokens=40))

    core.answer.side_effect = _blocking_answer
    semaphore = LazySemaphore(1)
    app = build_mcp_app(lambda _path: core, app_db_path, search_semaphore=semaphore)

    call = asyncio.ensure_future(
        app._server.call_tool("deep_search", {"question": "invoice"})
    )
    try:
        await anyio.to_thread.run_sync(in_answer.wait)
        call.cancel()
        with anyio.fail_after(1):
            with pytest.raises(asyncio.CancelledError):
                await call

        assert semaphore.acquire().locked()  # type: ignore[attr-defined]
        assert _tokens_used(app_db_path) == 0
    finally:
        release.set()

    with anyio.fail_after(5):
        async with semaphore.acquire():
            pass
    assert _tokens_used(app_db_path) == 40


@pytest.mark.anyio
async def test_work_of_a_cancelled_deep_search_that_then_fails_is_logged_not_dropped(
    app_db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _make_core(max_concurrent=1, answer_tokens=40)
    in_answer = threading.Event()
    release = threading.Event()

    def _blocking_answer(**_kwargs):
        in_answer.set()
        release.wait(timeout=5)
        return make_search_result(stats=make_search_stats(total_tokens=40))

    async def _failing_record_usage(**_kwargs):
        raise RuntimeError("database is locked")

    core.answer.side_effect = _blocking_answer
    monkeypatch.setattr(mcp_server, "record_usage", _failing_record_usage)
    app = build_mcp_app(
        lambda _path: core, app_db_path, search_semaphore=LazySemaphore(1)
    )
    unhandled: list[dict] = []
    asyncio.get_running_loop().set_exception_handler(
        lambda _loop, context: unhandled.append(context)
    )

    call = asyncio.ensure_future(
        app._server.call_tool("deep_search", {"question": "invoice"})
    )
    with structlog.testing.capture_logs() as logs:
        try:
            await anyio.to_thread.run_sync(in_answer.wait)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
        finally:
            release.set()
        with anyio.fail_after(5):
            while mcp_server._in_flight:
                await asyncio.sleep(0)
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)

    assert unhandled == []
    failures = [e for e in logs if e["log_level"] == "error"]
    assert len(failures) == 1
    assert "database is locked" in str(failures[0]["exc_info"])


class _BilledLLMClient(ScriptedLLMClient):
    """Every chat call reports 30 tokens used."""

    def route(self, **kwargs: Any) -> Any:
        completion = super().route(**kwargs)
        completion.usage = SimpleNamespace(
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
            completion_tokens_details=None,
        )
        return completion


@pytest.mark.anyio
async def test_tokens_spent_before_a_failed_deep_search_count_against_the_key(
    app_db_path: str,
) -> None:
    from tests.helpers.mcp_client import connect_client

    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.side_effect = RuntimeError("store fault")
    store_reader.keyword_search.side_effect = RuntimeError("store fault")
    embedding_client = MagicMock()
    embedding_client.embed.return_value = [[0.1, 0.2, 0.3]]
    core = build_search_core(
        settings=make_search_settings(
            SEARCH_KEY_DAILY_TOKEN_QUOTA=QUOTA, SEARCH_CACHE_TTL_SECONDS=0
        ),
        llm_client=_BilledLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        ),
        store_reader=store_reader,
        embedding_client=embedding_client,
    )
    app = build_mcp_app(
        lambda _path: core, app_db_path, search_semaphore=LazySemaphore(4)
    )

    async with connect_client(app._server) as client:
        result = await client.call_tool(
            "deep_search", {"question": "when does my boiler warranty expire?"}
        )

    assert result.isError is True
    assert _tokens_used(app_db_path) == 30
