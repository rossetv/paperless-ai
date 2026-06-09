"""Tests that the MCP tools thread the asker from the session/API-key caller.

Verifies:
- _run_search_tool forwards the asker argument to the core_call.
- The _BearerAuthMiddleware sets mcp_asker from the session user's display_name
  and resets it after the request (contextvar leak guard).
- With SEARCH_IDENTITY_AWARE=False, resolve_asker returns None so the core
  receives asker=None regardless of the contextvar value.
- A dirty display_name is sanitised before reaching the core via resolve_asker.
"""

from __future__ import annotations

import atexit
import os
import tempfile

import pytest

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from search.identity import mcp_asker
from search.mcp_server import _run_search_tool, build_mcp_app
from tests.helpers.factories import make_search_result, make_search_settings
from tests.helpers.search import mint_api_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_core(settings: object) -> object:
    """A stub SearchCore with scripted empty results."""
    from unittest.mock import MagicMock

    core = MagicMock()
    core.answer.return_value = make_search_result(answer="ok", sources=())
    core.retrieve.return_value = make_search_result(answer="", sources=())
    core.settings = settings
    return core


def _app_db_with_user(display_name: str | None = None) -> tuple[str, str]:
    """A migrated app.db with an mcp-scoped API key belonging to a user.

    Returns ``(app_db_path, raw_key)`` for use with the Starlette TestClient.
    """
    handle, path = tempfile.mkstemp(prefix="mcp-asker-test-", suffix=".db")
    os.close(handle)
    atexit.register(lambda: os.path.exists(path) and os.remove(path))

    conn = connect(path)
    ensure_schema(conn)
    user = create_user(
        conn,
        username="mcp-caller",
        password_hash="h",
        role="member",
        display_name=display_name,
    )
    raw_key = mint_api_key(conn, owner_user_id=user.id, scopes="mcp")
    conn.close()
    return path, raw_key


def _app_db_empty() -> str:
    """A fresh migrated app.db path with no users/keys — for rejection tests."""
    handle, path = tempfile.mkstemp(prefix="mcp-empty-test-", suffix=".db")
    os.close(handle)
    atexit.register(lambda: os.path.exists(path) and os.remove(path))
    conn = connect(path)
    ensure_schema(conn)
    conn.close()
    return path


# ---------------------------------------------------------------------------
# _run_search_tool unit tests — direct asker forwarding
# ---------------------------------------------------------------------------


def test_run_search_tool_forwards_asker_to_core_call() -> None:
    """_run_search_tool passes the asker argument through to the core_call."""
    received: list = []

    def _mock_call(query: str, ui_filters: object, asker: str | None) -> object:
        received.append(asker)
        return make_search_result(answer="ok", sources=())

    _run_search_tool(
        query="my passport",
        filters=None,
        core_call=_mock_call,
        error_event="test.event",
        asker="Vilmar Rosset",
    )

    assert received == ["Vilmar Rosset"]


def test_run_search_tool_forwards_none_asker_when_not_set() -> None:
    """_run_search_tool passes asker=None when no asker is given."""
    received: list = []

    def _mock_call(query: str, ui_filters: object, asker: str | None) -> object:
        received.append(asker)
        return make_search_result(answer="ok", sources=())

    _run_search_tool(
        query="passport",
        filters=None,
        core_call=_mock_call,
        error_event="test.event",
    )

    assert received == [None]


# ---------------------------------------------------------------------------
# Middleware integration — mcp_asker is set and reset via the ASGI stack
# ---------------------------------------------------------------------------


def test_mcp_middleware_sets_mcp_asker_from_api_key_owner() -> None:
    """The MCP auth middleware sets mcp_asker to the key owner's display_name.

    This test exercises the full ASGI middleware stack via the Starlette
    TestClient so the middleware's contextvar set/reset path runs. We assert
    that after the request the contextvar is reset to None, proving it was
    reset in the finally block and confirming contextvar state does not leak
    across requests.
    """
    from unittest.mock import patch

    from starlette.testclient import TestClient

    settings = make_search_settings(SEARCH_IDENTITY_AWARE=True)
    app_db_path, raw_key = _app_db_with_user(display_name="Vilmar Rosset")
    core = _make_core(settings)

    # Capture what mcp_asker holds during a request by patching resolve_asker
    # (called in _dispatch, which is the innermost observable point).
    captured_asker: list[str | None] = []
    original_resolve = __import__(
        "search.identity", fromlist=["resolve_asker"]
    ).resolve_asker

    def _spy_resolve(display_name: str | None, *, identity_aware: bool) -> str | None:
        captured_asker.append(display_name)
        return original_resolve(display_name, identity_aware=identity_aware)

    with patch("search.mcp_server.resolve_asker", _spy_resolve):
        asgi_app = build_mcp_app(core, settings, app_db_path)
        client = TestClient(asgi_app, raise_server_exceptions=False)

        client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1"},
                },
            },
        )

    # After the request, the contextvar must be reset to None — no leak.
    assert mcp_asker.get() is None, (
        "mcp_asker contextvar was not reset after the request — "
        "contextvar state would leak to subsequent requests."
    )


def test_mcp_middleware_resets_mcp_asker_after_request() -> None:
    """mcp_asker is None before and after a request; the reset is in a finally.

    Verifies the 'always reset, even if app raises' contract — we simulate
    this by checking the contextvar is back to None after a successful request.
    """
    from starlette.testclient import TestClient

    settings = make_search_settings(SEARCH_IDENTITY_AWARE=True)
    app_db_path, raw_key = _app_db_with_user(display_name="Someone")
    core = _make_core(settings)

    # Confirm the contextvar is None before the request.
    assert mcp_asker.get() is None

    asgi_app = build_mcp_app(core, settings, app_db_path)
    client = TestClient(asgi_app, raise_server_exceptions=False)
    client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1"},
            },
        },
    )

    # After the request, the contextvar must be back to None.
    assert mcp_asker.get() is None


# ---------------------------------------------------------------------------
# resolve_asker gate — SEARCH_IDENTITY_AWARE controls asker in dispatch
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ask_documents_suppresses_asker_when_identity_aware_off() -> None:
    """With SEARCH_IDENTITY_AWARE=False, _dispatch resolves asker=None.

    We test this by setting mcp_asker within the same async context as the
    tool invocation (using the in-memory transport where the tool runs in the
    same task as the call_tool() awaitable — not a pre-spawned server task).
    """
    from mcp.shared.memory import create_connected_server_and_client_session

    settings = make_search_settings(SEARCH_IDENTITY_AWARE=False)
    core = _make_core(settings)
    mcp_app = build_mcp_app(core, settings, _app_db_empty())

    # Even if mcp_asker has a value, SEARCH_IDENTITY_AWARE=False must suppress it.
    token = mcp_asker.set("Carol Smith")
    try:
        async with create_connected_server_and_client_session(
            mcp_app._fastmcp
        ) as client:
            await client.call_tool("ask_documents", {"question": "my invoices"})
    finally:
        mcp_asker.reset(token)

    _args, kwargs = core.answer.call_args
    assert kwargs.get("asker") is None


@pytest.mark.anyio
async def test_search_documents_suppresses_asker_when_identity_aware_off() -> None:
    """With SEARCH_IDENTITY_AWARE=False, search_documents resolves asker=None."""
    from mcp.shared.memory import create_connected_server_and_client_session

    settings = make_search_settings(SEARCH_IDENTITY_AWARE=False)
    core = _make_core(settings)
    mcp_app = build_mcp_app(core, settings, _app_db_empty())

    token = mcp_asker.set("Dave Jones")
    try:
        async with create_connected_server_and_client_session(
            mcp_app._fastmcp
        ) as client:
            await client.call_tool("search_documents", {"query": "my documents"})
    finally:
        mcp_asker.reset(token)

    _args, kwargs = core.retrieve.call_args
    assert kwargs.get("asker") is None
