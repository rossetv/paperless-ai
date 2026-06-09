"""Tests for the streaming search body ``search.routes._search_stream``.

Drives the body function directly (it returns a :class:`StreamingResponse`),
iterating ``resp.body_iterator`` and parsing each non-blank line as JSON. Two
contracts are pinned:

1. A pipeline that emits a ``PhaseStart`` then returns a ``SearchResult`` yields
   ordered ``phase_start`` … ``result`` frames with strictly increasing ``seq``.
2. A pipeline that raises yields a terminal ``error`` frame and the stream still
   closes (the sentinel always fires).

Both use ``@pytest.mark.anyio`` so the body runs on a real event loop (the queue
bridge depends on ``loop.call_soon_threadsafe`` from the worker thread).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from search.errors import LlmBudgetExceededError
from search.offload import LazySemaphore
from search.routes import _search_stream
from search.trace import PhaseStart
from search.wire import SearchRequest
from tests.helpers.factories import make_search_result


def _request(query: str = "when does my passport expire") -> SearchRequest:
    """A validated search request for the stream body."""
    return SearchRequest(query=query)


def _noop_semaphore() -> LazySemaphore:
    """An unbounded LazySemaphore — acquire() is a no-op context manager."""
    return LazySemaphore(0)


async def _lines(resp: Any) -> list[dict[str, object]]:
    """Drain a StreamingResponse body, parsing each non-blank line as JSON."""
    out: list[dict[str, object]] = []
    async for chunk in resp.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        for line in text.splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _emitting_core() -> MagicMock:
    """A stub core whose answer emits one PhaseStart then returns a result."""
    core = MagicMock()

    def _answer(*, query: str, ui_filters: Any, asker: Any, on_event: Any) -> Any:
        on_event(PhaseStart("plan", "Planning the query"))
        return make_search_result(answer="streamed answer")

    core.answer.side_effect = _answer
    return core


@pytest.mark.anyio
async def test_stream_yields_phase_then_result() -> None:
    """A PhaseStart-then-result run yields ordered frames with rising seq."""
    resp = await _search_stream(
        _request(), _emitting_core(), _noop_semaphore(), asker=None
    )
    lines = await _lines(resp)

    types = [obj["type"] for obj in lines]
    assert types[0] == "phase_start"
    assert types[-1] == "result"
    assert "phase_start" in types and "result" in types

    seqs = [obj["seq"] for obj in lines]
    assert all(seqs[i] < seqs[i + 1] for i in range(len(seqs) - 1)), seqs

    # The phase_start frame carries the emitted phase identity.
    start = next(obj for obj in lines if obj["type"] == "phase_start")
    assert start["phase"] == "plan"
    assert start["label"] == "Planning the query"

    # The result frame nests the full SearchResponse (answer + trace + cost).
    result = next(obj for obj in lines if obj["type"] == "result")
    body = result["result"]
    assert isinstance(body, dict)
    assert body["answer"] == "streamed answer"
    assert "trace" in body and "cost" in body


@pytest.mark.anyio
async def test_stream_emits_error_when_pipeline_raises() -> None:
    """A pipeline that raises yields a terminal error frame; the stream closes."""
    core = MagicMock()
    core.answer.side_effect = RuntimeError("pipeline exploded")

    resp = await _search_stream(_request(), core, _noop_semaphore(), asker=None)
    lines = await _lines(resp)

    # The stream still closed (we got here) and the last frame is the error.
    assert lines, "the stream must emit at least the error frame"
    assert lines[-1]["type"] == "error"
    assert lines[-1]["kind"] == "internal"
    # An internal failure never leaks the exception text to the client.
    assert lines[-1]["message"] == "search failed"
    # No result frame on the failure path.
    assert all(obj["type"] != "result" for obj in lines)


@pytest.mark.anyio
async def test_stream_emits_budget_error_frame() -> None:
    """A budget breach is surfaced as a 'budget' error frame, not 'internal'."""
    core = MagicMock()
    core.answer.side_effect = LlmBudgetExceededError("budget of 3 calls exceeded")

    resp = await _search_stream(_request(), core, _noop_semaphore(), asker=None)
    lines = await _lines(resp)

    assert lines[-1]["type"] == "error"
    assert lines[-1]["kind"] == "budget"
    # The budget message is the exception's own text (safe to surface).
    assert "budget" in lines[-1]["message"]


@pytest.mark.anyio
async def test_stream_records_recent_search_on_success() -> None:
    """On success the body records the caller's recent search via the worker."""
    recorded: list[tuple[int, str]] = []

    app_db = MagicMock()
    user = MagicMock()
    user.id = 7

    import search.routes as routes

    def _fake_record(conn: Any, *, user_id: int, query: str) -> None:
        recorded.append((user_id, query))

    original = routes.recent_search_store.record
    routes.recent_search_store.record = _fake_record  # type: ignore[assignment]
    try:
        resp = await _search_stream(
            _request("gas bill total"),
            _emitting_core(),
            _noop_semaphore(),
            asker=None,
            app_db=app_db,
            user=user,
        )
        lines = await _lines(resp)
    finally:
        routes.recent_search_store.record = original  # type: ignore[assignment]

    assert lines[-1]["type"] == "result"
    assert recorded == [(7, "gas bill total")]


@pytest.mark.anyio
async def test_stream_recording_failure_does_not_break_the_stream() -> None:
    """A recent-search write failure is swallowed; the result frame still lands."""
    app_db = MagicMock()
    user = MagicMock()
    user.id = 9

    import search.routes as routes

    def _boom(conn: Any, *, user_id: int, query: str) -> None:
        raise RuntimeError("recent_searches write failed")

    original = routes.recent_search_store.record
    routes.recent_search_store.record = _boom  # type: ignore[assignment]
    try:
        resp = await _search_stream(
            _request(),
            _emitting_core(),
            _noop_semaphore(),
            asker=None,
            app_db=app_db,
            user=user,
        )
        lines = await _lines(resp)
    finally:
        routes.recent_search_store.record = original  # type: ignore[assignment]

    # The result frame is unaffected by the recording failure.
    assert lines[-1]["type"] == "result"
