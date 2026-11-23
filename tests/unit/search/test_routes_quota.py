"""Tests for the API-key token quota on POST /api/search and its stream.

A real migrated app.db backs the quota reads and writes; the SearchCore is
stubbed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import search.routes as routes
from appdb.connection import connect
from appdb.key_usage import add_usage, get_tokens_used, utc_today
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from search.appstate import AppState, attach_app_state
from search.deps import get_current_user, require_role
from search.offload import LazySemaphore
from search.routes import _search_stream, build_api_router
from search.setup import SetupState
from search.wire import SearchRequest
from store import SchemaNotReadyError
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
from tests.helpers.search import build_search_core, mint_api_key

_QUOTA = 1000


def _app_db_with_key(tmp_path: Path) -> tuple[str, str, int]:
    """Migrate an app.db holding one API key; return (path, raw key, key id)."""
    path = str(tmp_path / "app.db")
    conn = connect(path)
    try:
        ensure_schema(conn)
        user = create_user(
            conn, username="api-user", password_hash="h", role="readonly"
        )
        raw_key = mint_api_key(conn, owner_user_id=user.id)
        key_id = conn.execute("SELECT id FROM api_keys").fetchone()["id"]
    finally:
        conn.close()
    return path, raw_key, key_id


def _tokens_used(path: str, key_id: int) -> int:
    conn = connect(path)
    try:
        return get_tokens_used(conn, key_id, utc_today())
    finally:
        conn.close()


def _spend(path: str, key_id: int, tokens: int) -> None:
    conn = connect(path)
    try:
        add_usage(conn, key_id, utc_today(), tokens=tokens, calls=1)
    finally:
        conn.close()


def _cached_core() -> MagicMock:
    """A stub core that serves a 500-token answer from its cache."""
    core = MagicMock()

    def _answer(*, on_cache_hit: Any = None, **_kwargs: Any) -> Any:
        if on_cache_hit is not None:
            on_cache_hit()
        return make_search_result(stats=make_search_stats(total_tokens=500))

    core.answer.side_effect = _answer
    return core


def _fresh_core() -> MagicMock:
    core = MagicMock()
    core.answer.return_value = make_search_result(
        stats=make_search_stats(total_tokens=500)
    )
    return core


_PLANNER_TOKENS = 300


class _BilledLLMClient(ScriptedLLMClient):
    """Every chat call reports :data:`_PLANNER_TOKENS` tokens used."""

    def route(self, **kwargs: Any) -> Any:
        completion = super().route(**kwargs)
        completion.usage = SimpleNamespace(
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=_PLANNER_TOKENS,
            completion_tokens_details=None,
        )
        return completion


def _core_failing_after_the_planner(error: Exception) -> Any:
    """A real pipeline whose planner bills tokens and whose retrieval raises."""
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.side_effect = error
    store_reader.keyword_search.side_effect = error
    embedding_client = MagicMock()
    embedding_client.embed.return_value = [[0.1, 0.2, 0.3]]
    return build_search_core(
        settings=make_search_settings(SEARCH_CACHE_TTL_SECONDS=0),
        llm_client=_BilledLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        ),
        store_reader=store_reader,
        embedding_client=embedding_client,
    )


class _EmptyReplyLLMClient(_BilledLLMClient):
    """Bills every call, but the planner's reply carries no choices."""

    def route(self, **kwargs: Any) -> Any:
        completion = super().route(**kwargs)
        completion.choices = []
        return completion


def _core_failing_inside_the_planner() -> Any:
    """A real pipeline whose planner call bills tokens and then raises."""
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    return build_search_core(
        settings=make_search_settings(SEARCH_CACHE_TTL_SECONDS=0),
        llm_client=_EmptyReplyLLMClient(
            planner_response=planner_response_json(),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        ),
        store_reader=store_reader,
        embedding_client=MagicMock(),
    )


def _client(path: str, core: MagicMock) -> TestClient:
    settings = make_search_settings(
        APP_DB_PATH=path, SEARCH_KEY_DAILY_TOKEN_QUOTA=_QUOTA
    )
    core.settings = settings
    app = FastAPI()
    attach_app_state(app.state, AppState(app_db_path=path, setup_state=SetupState()))
    app.include_router(
        build_api_router(
            settings,
            lambda _path: core,
            MagicMock(),
            require_reader=require_role("readonly"),
            require_member=require_role("member"),
            get_current_user=get_current_user,
            search_semaphore=LazySemaphore(4),
            current_settings=lambda: settings,
        )
    )
    return TestClient(app, raise_server_exceptions=False, base_url="https://testserver")


async def _lines(resp: Any) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    async for chunk in resp.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        out.extend(json.loads(line) for line in text.splitlines() if line.strip())
    return out


def test_cached_answer_charges_no_tokens_but_reports_its_cost(tmp_path: Path) -> None:
    path, raw_key, key_id = _app_db_with_key(tmp_path)
    client = _client(path, _cached_core())

    response = client.post(
        "/api/search",
        json={"query": "gas bill"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 200
    assert response.json()["cost"]["tokens"]["total"] == 500
    assert _tokens_used(path, key_id) == 0


@pytest.mark.anyio
async def test_cached_streamed_answer_charges_no_tokens(tmp_path: Path) -> None:
    path, _raw_key, key_id = _app_db_with_key(tmp_path)

    resp = await _search_stream(
        SearchRequest(query="gas bill"),
        _cached_core(),
        LazySemaphore(1),
        app_db_path=path,
        api_key_id=key_id,
        quota=_QUOTA,
    )
    lines = await _lines(resp)

    assert lines[-1]["type"] == "result"
    assert _tokens_used(path, key_id) == 0


def test_quota_spent_while_waiting_for_a_slot_gets_429(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, raw_key, key_id = _app_db_with_key(tmp_path)
    real_check = routes.check_quota

    async def _check_then_others_spend(**kwargs: Any) -> None:
        await real_check(**kwargs)
        # Parallel requests use up the day's quota after this one's early check.
        _spend(path, key_id, _QUOTA)

    monkeypatch.setattr(routes, "check_quota", _check_then_others_spend)
    core = _fresh_core()
    client = _client(path, core)

    response = client.post(
        "/api/search",
        json={"query": "gas bill"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    core.answer.assert_not_called()


@pytest.mark.anyio
async def test_stream_refused_at_the_slot_ends_with_a_quota_error_frame(
    tmp_path: Path,
) -> None:
    path, _raw_key, key_id = _app_db_with_key(tmp_path)
    _spend(path, key_id, _QUOTA)
    core = _fresh_core()
    semaphore = LazySemaphore(1)

    resp = await _search_stream(
        SearchRequest(query="gas bill"),
        core,
        semaphore,
        app_db_path=path,
        api_key_id=key_id,
        quota=_QUOTA,
    )
    lines = await _lines(resp)

    assert [(line["type"], line["kind"]) for line in lines] == [("error", "quota")]
    core.answer.assert_not_called()
    assert not semaphore.acquire().locked()  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_waiting_search_is_refused_when_the_first_fills_the_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _raw_key, key_id = _app_db_with_key(tmp_path)
    real_record = routes.record_usage

    async def _slow_record(**kwargs: Any) -> None:
        await asyncio.sleep(0.05)
        await real_record(**kwargs)

    monkeypatch.setattr(routes, "record_usage", _slow_record)
    first, second = _fresh_core(), _fresh_core()
    first.answer.return_value = make_search_result(
        stats=make_search_stats(total_tokens=_QUOTA)
    )
    semaphore = LazySemaphore(1)

    def _run(core: MagicMock) -> Any:
        return routes._search(
            SearchRequest(query="gas bill"),
            core,
            semaphore,
            asker=None,
            app_db_path=path,
            api_key_id=key_id,
            quota=_QUOTA,
        )

    results = await asyncio.gather(_run(first), _run(second), return_exceptions=True)

    assert not isinstance(results[0], BaseException)
    assert isinstance(results[1], HTTPException)
    assert results[1].status_code == 429
    second.answer.assert_not_called()


@pytest.mark.anyio
async def test_tokens_spent_before_a_failed_search_count_against_the_key(
    tmp_path: Path,
) -> None:
    path, _raw_key, key_id = _app_db_with_key(tmp_path)
    core = _core_failing_after_the_planner(SchemaNotReadyError("rebuilding"))

    with pytest.raises(HTTPException) as raised:
        await routes._search(
            SearchRequest(query="when does my boiler warranty expire?"),
            core,
            LazySemaphore(1),
            asker=None,
            app_db_path=path,
            api_key_id=key_id,
            quota=_QUOTA,
        )

    assert raised.value.status_code == 503
    assert _tokens_used(path, key_id) == _PLANNER_TOKENS


@pytest.mark.anyio
async def test_tokens_spent_before_a_failed_stream_count_against_the_key(
    tmp_path: Path,
) -> None:
    path, _raw_key, key_id = _app_db_with_key(tmp_path)
    core = _core_failing_after_the_planner(RuntimeError("store fault"))

    resp = await _search_stream(
        SearchRequest(query="when does my boiler warranty expire?"),
        core,
        LazySemaphore(1),
        app_db_path=path,
        api_key_id=key_id,
        quota=_QUOTA,
    )
    lines = await _lines(resp)

    assert (lines[-1]["type"], lines[-1]["kind"]) == ("error", "internal")
    assert _tokens_used(path, key_id) == _PLANNER_TOKENS


@pytest.mark.anyio
async def test_tokens_spent_inside_the_phase_that_fails_count_against_the_key(
    tmp_path: Path,
) -> None:
    path, _raw_key, key_id = _app_db_with_key(tmp_path)

    with pytest.raises(IndexError):
        await routes._search(
            SearchRequest(query="when does my boiler warranty expire?"),
            _core_failing_inside_the_planner(),
            LazySemaphore(1),
            asker=None,
            app_db_path=path,
            api_key_id=key_id,
            quota=_QUOTA,
        )

    assert _tokens_used(path, key_id) == _PLANNER_TOKENS


@pytest.mark.anyio
async def test_tokens_spent_inside_the_phase_that_fails_a_stream_count_against_the_key(
    tmp_path: Path,
) -> None:
    path, _raw_key, key_id = _app_db_with_key(tmp_path)

    resp = await _search_stream(
        SearchRequest(query="when does my boiler warranty expire?"),
        _core_failing_inside_the_planner(),
        LazySemaphore(1),
        app_db_path=path,
        api_key_id=key_id,
        quota=_QUOTA,
    )
    lines = await _lines(resp)

    assert (lines[-1]["type"], lines[-1]["kind"]) == ("error", "internal")
    assert _tokens_used(path, key_id) == _PLANNER_TOKENS
