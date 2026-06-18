"""The MCP endpoint must be live over the real ASGI mount (regression).

Two wiring bugs once made ``/mcp`` non-functional in production while every
existing test stayed green:

1. **Double prefix.** ``create_app`` mounts the MCP app under ``/mcp`` while
   ``FastMCP.streamable_http_app()`` *also* served at its default ``/mcp``, so
   the live endpoint was ``/mcp/mcp`` and ``/mcp`` fell through to the SPA
   catch-all (405 to a POST).
2. **Dead task group.** A mounted ASGI sub-app's lifespan is never run by the
   parent, so the streamable session manager's task group was never started and
   every authenticated request raised ``RuntimeError: Task group is not
   initialized`` → HTTP 500.

Neither surfaced because the unit tests drive ``build_mcp_app`` *standalone*
(no mount, no lifespan) and assert only the 401 auth boundary, while the
protocol round-trips use the in-memory transport (no HTTP, no session manager).

This test closes that gap: it builds the **whole** app via ``create_app``,
runs the lifespan (the ``with TestClient(...)`` context manager), authenticates
with an ``mcp``-scoped API key, and POSTs a real ``initialize`` to ``/mcp``.
A 200 is reachable only when the path is exactly ``/mcp`` *and* the session
manager's task group is live — it fails on 404 (wrong path), 405 (SPA
catch-all), and 500 (dead task group) alike.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from search.api import create_app
from store.reader import StoreReader
from tests.integration.accounts_helpers import (
    make_mock_core,
    make_settings,
    open_app_db,
    seed_store,
    seed_user,
)
from tests.helpers.search import mint_api_key

# The streamable-HTTP transport requires the client to accept BOTH media types;
# omitting either yields 406 Not Acceptable before the handler runs.
_MCP_ACCEPT = "application/json, text/event-stream"
_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "regression", "version": "0"},
    },
}


def test_mcp_initialize_succeeds_through_the_real_mount(tmp_path: Path) -> None:
    """An authenticated ``initialize`` POST to ``/mcp`` returns 200, not 404/405/500."""
    settings = make_settings(tmp_path)
    seed_store(settings)

    app_db = open_app_db(tmp_path)
    try:
        user = seed_user(app_db, username="agent", role="member")
        raw_key = mint_api_key(app_db, owner_user_id=user.id, scopes="mcp")
    finally:
        app_db.close()

    app = create_app(
        settings, core=make_mock_core(), store_reader=StoreReader(settings)
    )

    # The context manager runs the app's lifespan, which starts the MCP session
    # manager's task group — without it the request 500s (bug 2).
    with TestClient(
        app, raise_server_exceptions=False, base_url="https://testserver"
    ) as client:
        response = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Accept": _MCP_ACCEPT,
            },
            json=_INITIALIZE,
        )

    assert response.status_code == 200, (
        f"/mcp initialize returned {response.status_code}, not 200 "
        f"(404=wrong path, 405=SPA catch-all, 500=dead task group): {response.text!r}"
    )
    # The initialize result carries the server's identity — proof the request
    # reached the live MCP handler, not a stray 200 from elsewhere.
    assert "paperless-search" in response.text
