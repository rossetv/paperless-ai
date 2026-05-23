"""Tests for search.mcp_server — the MCP endpoint (spec §7.2/§7.3).

Covers the public contract of ``build_mcp_app``:

- ``search_documents`` calls ``core.retrieve`` and returns sources without an
  answer.
- ``ask_documents`` calls ``core.answer`` and returns the full result (answer +
  sources).
- An unauthenticated MCP request is rejected with HTTP 401 before any tool runs.
- An ``mcp``-scoped API key authenticates; a key without the ``mcp`` scope is
  rejected with HTTP 401 (web-redesign §5).
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

# A junk bearer that resolves to no api_keys row — used by the rejection tests.
_WRONG_KEY = "sk-pls-this-key-was-never-minted"


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


def _make_settings() -> MagicMock:
    """Create a Settings-like mock for the MCP server.

    ``settings`` is passed to ``build_mcp_app`` but the auth middleware does
    not read any setting directly — authentication is by session cookie or
    ``mcp``-scoped API key (web-redesign §5).
    """
    return make_search_settings()


def _make_core(
    retrieve_result: SearchResult | None = None,
    answer_result: SearchResult | None = None,
) -> MagicMock:
    """Create a SearchCore stub returning scripted results."""
    core = MagicMock()
    core.retrieve.return_value = retrieve_result or _retrieve_result()
    core.answer.return_value = answer_result or _answer_result()
    return core


def _app_db_path() -> str:
    """A fresh migrated app.db file for MCP auth tests, returning its path.

    ``build_mcp_app`` takes the ``app.db`` *path*; its auth middleware opens a
    connection per request to resolve a session cookie or an API key. This
    helper yields an empty migrated database — every credential check against
    it fails, so it backs the unauthenticated / junk-bearer rejection tests.
    The file is removed at process exit.
    """
    import atexit
    import os
    import tempfile

    from appdb.connection import connect
    from appdb.schema import ensure_schema

    handle, path = tempfile.mkstemp(prefix="mcp-test-app-", suffix=".db")
    os.close(handle)
    atexit.register(lambda: os.path.exists(path) and os.remove(path))
    conn = connect(path)
    ensure_schema(conn)
    conn.close()
    return path


def _app_db_with_key(scopes: str = "mcp") -> tuple[str, str]:
    """A migrated app.db file holding an owner and one API key.

    Mirrors the ``app.db`` an authenticated MCP request resolves against: a
    Member owner plus a single API key with the given *scopes*. The middleware
    opens its own connection on the returned path, so the key is persisted and
    committed before the path is handed back.

    Args:
        scopes: The comma-separated scope string for the minted key. Defaults
            to ``"mcp"``; pass ``"api"`` to mint a key the MCP gate rejects.

    Returns:
        A ``(app_db_path, raw_key)`` pair — the database path for
        ``build_mcp_app`` and the full raw key to send as a bearer token.
    """
    from appdb.api_keys import create as create_key
    from appdb.connection import connect
    from appdb.users import create as create_user
    from search.api_keys import generate_raw_key, hash_key, key_display_prefix

    path = _app_db_path()
    raw = generate_raw_key()
    conn = connect(path)
    try:
        create_user(
            conn,
            username="mcp-owner",
            password_hash="h",
            role="member",
        )
        create_key(
            conn,
            key_hash=hash_key(raw),
            key_prefix=key_display_prefix(raw),
            name="mcp",
            owner_user_id=1,
            scopes=scopes,
        )
    finally:
        conn.close()
    return path, raw


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

    mcp_app = build_mcp_app(core, settings, _app_db_path())

    async with create_connected_server_and_client_session(
        mcp_app._fastmcp  # access the FastMCP instance for in-memory transport
    ) as client:
        result = await client.call_tool("search_documents", {"query": "invoice 2024"})

    core.retrieve.assert_called_once()
    call_args = core.retrieve.call_args
    assert (
        call_args.kwargs.get("query") == "invoice 2024"
        or call_args.args[0] == "invoice 2024"
    )

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

    mcp_app = build_mcp_app(core, settings, _app_db_path())

    async with create_connected_server_and_client_session(mcp_app._fastmcp) as client:
        result = await client.call_tool(
            "ask_documents", {"question": "What does the invoice cover?"}
        )

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

    mcp_app = build_mcp_app(core, settings, _app_db_path())

    async with create_connected_server_and_client_session(mcp_app._fastmcp) as client:
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

    mcp_app = build_mcp_app(core, settings, _app_db_path())

    async with create_connected_server_and_client_session(mcp_app._fastmcp) as client:
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

    mcp_app = build_mcp_app(core, settings, _app_db_path())

    async with create_connected_server_and_client_session(mcp_app._fastmcp) as client:
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

    mcp_app = build_mcp_app(core, settings, _app_db_path())

    async with create_connected_server_and_client_session(mcp_app._fastmcp) as client:
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

    asgi_app = build_mcp_app(core, settings, _app_db_path())
    client = TestClient(asgi_app, raise_server_exceptions=False)

    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1}
    )

    assert response.status_code == 401


def test_wrong_bearer_token_is_rejected_with_401() -> None:
    """An MCP request with a wrong bearer token is rejected with HTTP 401."""
    core = _make_core()
    settings = _make_settings()

    asgi_app = build_mcp_app(core, settings, _app_db_path())
    client = TestClient(asgi_app, raise_server_exceptions=False)

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {_WRONG_KEY}"},
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )

    assert response.status_code == 401


def test_mcp_scoped_api_key_passes_auth_layer() -> None:
    """An MCP request with an ``mcp``-scoped API key reaches the handler (not 401)."""
    core = _make_core()
    settings = _make_settings()
    app_db_path, raw_key = _app_db_with_key(scopes="mcp")

    asgi_app = build_mcp_app(core, settings, app_db_path)
    client = TestClient(asgi_app, raise_server_exceptions=False)

    response = client.post(
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

    # Any response other than 401 means auth passed (may be 200, 202, 406, etc.)
    assert response.status_code != 401


def test_api_key_without_mcp_scope_is_rejected_with_401() -> None:
    """An API key lacking the ``mcp`` scope cannot reach /mcp (web-redesign §5)."""
    core = _make_core()
    settings = _make_settings()
    # An "api"-only key: valid for the data routes, but not for the MCP surface.
    app_db_path, raw_key = _app_db_with_key(scopes="api")

    asgi_app = build_mcp_app(core, settings, app_db_path)
    client = TestClient(asgi_app, raise_server_exceptions=False)

    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )

    assert response.status_code == 401


def test_no_bearer_prefix_is_rejected() -> None:
    """A raw token without 'Bearer ' prefix is rejected with HTTP 401."""
    core = _make_core()
    settings = _make_settings()
    # A real mcp-scoped key exists, but the header omits the 'Bearer ' prefix,
    # so extract_bearer yields None and the key is never looked up.
    app_db_path, raw_key = _app_db_with_key(scopes="mcp")

    asgi_app = build_mcp_app(core, settings, app_db_path)
    client = TestClient(asgi_app, raise_server_exceptions=False)

    # Send the key directly, without the 'Bearer ' prefix.
    response = client.post(
        "/mcp",
        headers={"Authorization": raw_key},
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# MAJOR-1 regression — cookie auth must refresh last_seen_at
# ---------------------------------------------------------------------------


def test_cookie_auth_refreshes_last_seen_at() -> None:
    """A session-cookie MCP request must bump last_seen_at (MAJOR-1).

    Before Wave 3 the MCP middleware called refresh_last_seen on a successful
    cookie auth. Wave 3 regressed this by dropping the call. This test fails
    if the second request does not update last_seen_at.

    Strategy: create a session with a last_seen_at far in the past (beyond
    the ~5-minute throttle window), issue two MCP requests with the cookie,
    then assert the stored last_seen_at has moved forward.
    """
    from datetime import datetime, timedelta, timezone

    from appdb.connection import connect
    from appdb.schema import ensure_schema
    from appdb.sessions import get_by_token_hash
    from appdb.users import create as create_user
    from search.auth import SESSION_COOKIE_NAME
    from search.sessions import begin_session, hash_token

    import atexit
    import os
    import tempfile

    # Build a real app.db with a user and a session.
    handle, path = tempfile.mkstemp(prefix="mcp-seen-test-", suffix=".db")
    os.close(handle)
    atexit.register(lambda: os.path.exists(path) and os.remove(path))

    conn = connect(path)
    ensure_schema(conn)
    create_user(conn, username="cookie-user", password_hash="h", role="member")
    issued = begin_session(conn, user_id=1, ttl_seconds=3600)
    # Force last_seen_at to be stale — 10 minutes in the past.
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
        (stale, hash_token(issued.token)),
    )
    conn.commit()
    conn.close()

    core = _make_core()
    settings = _make_settings()
    asgi_app = build_mcp_app(core, settings, path)
    client = TestClient(asgi_app, raise_server_exceptions=False)

    # First request — should pass auth and trigger a last_seen_at refresh.
    client.post(
        "/mcp",
        cookies={SESSION_COOKIE_NAME: issued.token},
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

    # Read last_seen_at after the request.
    conn2 = connect(path)
    row = get_by_token_hash(conn2, hash_token(issued.token))
    conn2.close()

    assert row is not None, "Session row vanished"
    assert row.last_seen_at != stale, (
        f"last_seen_at was not refreshed: still {row.last_seen_at!r}"
    )


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

    mcp_app = build_mcp_app(core, settings, _app_db_path())

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

    mcp_app = build_mcp_app(core, settings, _app_db_path())

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

    mcp_app = build_mcp_app(core, settings, _app_db_path())

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

    mcp_app = build_mcp_app(core, settings, _app_db_path())

    too_long = "x" * 4001

    async with create_connected_server_and_client_session(mcp_app._fastmcp) as client:
        result = await client.call_tool("ask_documents", {"question": too_long})

    assert result.isError is True
    core.answer.assert_not_called()
    error_text = " ".join(
        block.text for block in result.content if hasattr(block, "text")
    )
    assert "4000" in error_text or "maximum" in error_text.lower()
