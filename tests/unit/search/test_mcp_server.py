"""Tests for search.mcp_server — the MCP endpoint (spec §7.2/§7.3).

Covers the public contract of ``build_mcp_app``:

- ``search_documents`` calls ``core.retrieve`` and returns sources without an
  answer.
- ``ask_documents`` calls ``core.answer`` and returns the full result (answer +
  sources).
- An unauthenticated MCP request is rejected with HTTP 401 before any tool runs.
- A tool call with a missing required argument is rejected cleanly (MCP error,
  not a server crash).
- A core exception carrying a filesystem path does not leak the path to the
  MCP client (I3).
- An over-length query/question is rejected with a clean tool error (MINOR 2).

The MCP protocol tests use ``create_connected_server_and_client_session`` from
``mcp.shared.memory`` for an in-process, transport-layer-free round-trip.
Authentication tests use Starlette's ``TestClient`` against the ASGI app
returned by ``build_mcp_app``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from search.mcp_server import build_mcp_app
from search.models import SearchResult
from tests.helpers.factories import (
    make_search_result,
    make_search_settings,
    make_source_document,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_KEY = "test-search-api-key"
_VALID_AUTH_HEADER = f"Bearer {_API_KEY}"
_WRONG_KEY = "wrong-key"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _retrieve_result() -> SearchResult:
    """A retrieve() result — no answer, just one source."""
    return make_search_result(
        answer="",
        sources=(make_source_document(document_id=42, title="Invoice 2024"),),
        stats=None,
    )


def _answer_result() -> SearchResult:
    """An answer() result — a synthesised answer plus one source."""
    return make_search_result(
        answer="The invoice from Acme Ltd covers services rendered in January 2024.",
        sources=(make_source_document(document_id=42, title="Invoice 2024"),),
    )


def _make_settings(api_key: str = _API_KEY) -> MagicMock:
    """Create a Settings-like mock for the MCP server, with a chosen API key."""
    return make_search_settings(SEARCH_API_KEY=api_key)


def _make_core(
    retrieve_result: SearchResult | None = None,
    answer_result: SearchResult | None = None,
) -> MagicMock:
    """Create a SearchCore stub returning scripted results."""
    core = MagicMock()
    core.retrieve.return_value = retrieve_result or _retrieve_result()
    core.answer.return_value = answer_result or _answer_result()
    return core


def _app_db() -> object:
    """A fresh migrated in-memory app.db for MCP auth tests.

    ``build_mcp_app`` needs the connection so its auth middleware can resolve a
    browser session cookie. These unit tests only exercise the legacy-bearer
    path, so an empty (user-less) database is enough.
    """
    from appdb.connection import connect
    from appdb.schema import ensure_schema

    conn = connect(":memory:")
    ensure_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# In-process MCP tool tests (via in-memory transport)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_documents_calls_retrieve_and_returns_sources() -> None:
    """search_documents invokes core.retrieve and exposes sources without answer."""
    from mcp.shared.memory import create_connected_server_and_client_session

    retrieve_result = _retrieve_result()
    core = _make_core(retrieve_result=retrieve_result)
    settings = _make_settings()

    mcp_app = build_mcp_app(core, settings, _app_db())

    async with create_connected_server_and_client_session(
        mcp_app._fastmcp  # access the FastMCP instance for in-memory transport
    ) as client:
        result = await client.call_tool("search_documents", {"query": "invoice 2024"})

    core.retrieve.assert_called_once()
    call_args = core.retrieve.call_args
    assert call_args.kwargs.get("query") == "invoice 2024" or call_args.args[0] == "invoice 2024"

    assert result.content
    payload = json.loads(result.content[0].text)
    assert payload["answer"] == ""
    assert len(payload["sources"]) == 1
    assert payload["sources"][0]["document_id"] == 42
    assert payload["sources"][0]["title"] == "Invoice 2024"


@pytest.mark.anyio
async def test_ask_documents_calls_answer_and_returns_full_result() -> None:
    """ask_documents invokes core.answer and returns answer + sources."""
    from mcp.shared.memory import create_connected_server_and_client_session

    answer_result = _answer_result()
    core = _make_core(answer_result=answer_result)
    settings = _make_settings()

    mcp_app = build_mcp_app(core, settings, _app_db())

    async with create_connected_server_and_client_session(
        mcp_app._fastmcp
    ) as client:
        result = await client.call_tool("ask_documents", {"question": "What does the invoice cover?"})

    core.answer.assert_called_once()
    call_args = core.answer.call_args
    assert (
        call_args.kwargs.get("query") == "What does the invoice cover?"
        or call_args.args[0] == "What does the invoice cover?"
    )

    assert result.content
    payload = json.loads(result.content[0].text)
    assert "Acme Ltd" in payload["answer"]
    assert len(payload["sources"]) == 1
    assert payload["sources"][0]["document_id"] == 42
    assert payload["stats"]["llm_calls"] == 2


@pytest.mark.anyio
async def test_search_documents_with_no_filters_passes_none_ui_filters() -> None:
    """search_documents with no filters argument passes ui_filters=None."""
    from mcp.shared.memory import create_connected_server_and_client_session

    core = _make_core()
    settings = _make_settings()

    mcp_app = build_mcp_app(core, settings, _app_db())

    async with create_connected_server_and_client_session(
        mcp_app._fastmcp
    ) as client:
        await client.call_tool("search_documents", {"query": "boiler warranty"})

    core.retrieve.assert_called_once()
    call_kwargs = core.retrieve.call_args
    # ui_filters should be None when not supplied
    ui_filters = call_kwargs.kwargs.get("ui_filters") or (
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
    )
    assert ui_filters is None


@pytest.mark.anyio
async def test_ask_documents_with_no_filters_passes_none_ui_filters() -> None:
    """ask_documents with no filters argument passes ui_filters=None."""
    from mcp.shared.memory import create_connected_server_and_client_session

    core = _make_core()
    settings = _make_settings()

    mcp_app = build_mcp_app(core, settings, _app_db())

    async with create_connected_server_and_client_session(
        mcp_app._fastmcp
    ) as client:
        await client.call_tool("ask_documents", {"question": "What is my name?"})

    core.answer.assert_called_once()
    call_kwargs = core.answer.call_args
    ui_filters = call_kwargs.kwargs.get("ui_filters") or (
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
    )
    assert ui_filters is None


@pytest.mark.anyio
async def test_search_documents_missing_required_query_is_rejected() -> None:
    """A call to search_documents without the required 'query' argument is rejected.

    FastMCP validates required arguments and returns an error result
    (``isError=True``) rather than raising an exception, as per the MCP
    protocol's tool-error mechanism.
    """
    from mcp.shared.memory import create_connected_server_and_client_session

    core = _make_core()
    settings = _make_settings()

    mcp_app = build_mcp_app(core, settings, _app_db())

    async with create_connected_server_and_client_session(
        mcp_app._fastmcp
    ) as client:
        result = await client.call_tool("search_documents", {})  # missing 'query'

    assert result.isError is True
    # core.retrieve must not have been called — the error is pre-call.
    core.retrieve.assert_not_called()


@pytest.mark.anyio
async def test_ask_documents_missing_required_question_is_rejected() -> None:
    """A call to ask_documents without the required 'question' argument is rejected.

    FastMCP validates required arguments and returns an error result
    (``isError=True``) rather than raising an exception.
    """
    from mcp.shared.memory import create_connected_server_and_client_session

    core = _make_core()
    settings = _make_settings()

    mcp_app = build_mcp_app(core, settings, _app_db())

    async with create_connected_server_and_client_session(
        mcp_app._fastmcp
    ) as client:
        result = await client.call_tool("ask_documents", {})  # missing 'question'

    assert result.isError is True
    # core.answer must not have been called — the error is pre-call.
    core.answer.assert_not_called()


# ---------------------------------------------------------------------------
# Authentication middleware tests (via Starlette TestClient)
# ---------------------------------------------------------------------------


def test_unauthenticated_request_is_rejected_with_401() -> None:
    """An MCP POST with no Authorization header is rejected with HTTP 401."""
    core = _make_core()
    settings = _make_settings()

    asgi_app = build_mcp_app(core, settings, _app_db())
    client = TestClient(asgi_app, raise_server_exceptions=False)

    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})

    assert response.status_code == 401


def test_wrong_bearer_token_is_rejected_with_401() -> None:
    """An MCP request with a wrong bearer token is rejected with HTTP 401."""
    core = _make_core()
    settings = _make_settings()

    asgi_app = build_mcp_app(core, settings, _app_db())
    client = TestClient(asgi_app, raise_server_exceptions=False)

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {_WRONG_KEY}"},
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )

    assert response.status_code == 401


def test_valid_bearer_token_passes_auth_layer() -> None:
    """An MCP request with a valid bearer token reaches the MCP handler (not 401)."""
    core = _make_core()
    settings = _make_settings()

    asgi_app = build_mcp_app(core, settings, _app_db())
    client = TestClient(asgi_app, raise_server_exceptions=False)

    response = client.post(
        "/mcp",
        headers={"Authorization": _VALID_AUTH_HEADER},
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0.1"},
        }},
    )

    # Any response other than 401 means auth passed (may be 200, 202, 406, etc.)
    assert response.status_code != 401


def test_no_bearer_prefix_is_rejected() -> None:
    """A raw token without 'Bearer ' prefix is rejected with HTTP 401."""
    core = _make_core()
    settings = _make_settings()

    asgi_app = build_mcp_app(core, settings, _app_db())
    client = TestClient(asgi_app, raise_server_exceptions=False)

    # Send the key directly, without the 'Bearer ' prefix.
    response = client.post(
        "/mcp",
        headers={"Authorization": _API_KEY},
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# I3 regression — core exceptions must not leak internals to the MCP client
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_documents_core_exception_does_not_leak_path() -> None:
    """search_documents must not expose filesystem paths in error text (I3).

    When ``core.retrieve`` raises an exception whose message contains a
    filesystem path, the tool result must NOT include that path — only a
    generic sanitised message.  This test fails if the bare ``str(exc)`` is
    returned to the caller.
    """
    from mcp.shared.memory import create_connected_server_and_client_session

    secret_path = "/var/data/paperless/index.db"

    core = MagicMock()
    core.retrieve.side_effect = RuntimeError(
        f"sqlite3 error opening {secret_path}: no such file"
    )
    settings = _make_settings()

    mcp_app = build_mcp_app(core, settings, _app_db())

    async with create_connected_server_and_client_session(mcp_app._fastmcp) as client:
        result = await client.call_tool("search_documents", {"query": "test"})

    assert result.isError is True
    # The raw filesystem path must never reach the client.
    error_text = " ".join(
        block.text for block in result.content if hasattr(block, "text")
    )
    assert secret_path not in error_text, (
        f"Filesystem path leaked to MCP client: {error_text!r}"
    )
    # A generic sanitised message must be present instead.
    assert "search failed" in error_text.lower() or "error" in error_text.lower()


@pytest.mark.anyio
async def test_ask_documents_core_exception_does_not_leak_path() -> None:
    """ask_documents must not expose filesystem paths in error text (I3).

    Mirrors ``test_search_documents_core_exception_does_not_leak_path`` for
    the ``ask_documents`` tool.
    """
    from mcp.shared.memory import create_connected_server_and_client_session

    secret_path = "/var/data/paperless/index.db"

    core = MagicMock()
    core.answer.side_effect = RuntimeError(
        f"sqlite3 error opening {secret_path}: no such file"
    )
    settings = _make_settings()

    mcp_app = build_mcp_app(core, settings, _app_db())

    async with create_connected_server_and_client_session(mcp_app._fastmcp) as client:
        result = await client.call_tool("ask_documents", {"question": "test"})

    assert result.isError is True
    error_text = " ".join(
        block.text for block in result.content if hasattr(block, "text")
    )
    assert secret_path not in error_text, (
        f"Filesystem path leaked to MCP client: {error_text!r}"
    )
    assert "search failed" in error_text.lower() or "error" in error_text.lower()


# ---------------------------------------------------------------------------
# MINOR 2 regression — over-length queries are rejected at the MCP boundary
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_documents_rejects_over_length_query() -> None:
    """search_documents must reject a query exceeding 4000 characters (MINOR 2)."""
    from mcp.shared.memory import create_connected_server_and_client_session

    core = _make_core()
    settings = _make_settings()

    mcp_app = build_mcp_app(core, settings, _app_db())

    too_long = "x" * 4001

    async with create_connected_server_and_client_session(mcp_app._fastmcp) as client:
        result = await client.call_tool("search_documents", {"query": too_long})

    assert result.isError is True
    # core.retrieve must NOT have been called — rejection is at the boundary.
    core.retrieve.assert_not_called()
    error_text = " ".join(
        block.text for block in result.content if hasattr(block, "text")
    )
    assert "4000" in error_text or "maximum" in error_text.lower()


@pytest.mark.anyio
async def test_ask_documents_rejects_over_length_question() -> None:
    """ask_documents must reject a question exceeding 4000 characters (MINOR 2)."""
    from mcp.shared.memory import create_connected_server_and_client_session

    core = _make_core()
    settings = _make_settings()

    mcp_app = build_mcp_app(core, settings, _app_db())

    too_long = "x" * 4001

    async with create_connected_server_and_client_session(mcp_app._fastmcp) as client:
        result = await client.call_tool("ask_documents", {"question": too_long})

    assert result.isError is True
    core.answer.assert_not_called()
    error_text = " ".join(
        block.text for block in result.content if hasattr(block, "text")
    )
    assert "4000" in error_text or "maximum" in error_text.lower()
