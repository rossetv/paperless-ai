"""Regression test: the MCP endpoint must be live over the real ASGI mount.

Unit tests drive ``build_mcp_app`` standalone, so they miss two wiring failures:
a doubled ``/mcp/mcp`` path that lets ``/mcp`` fall through to the SPA
catch-all, and a mounted sub-app whose lifespan never starts the session
manager's task group (500). A real ``initialize`` returns 200 only when both
are right.
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

# The streamable-HTTP transport requires the client to accept both media types;
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

    # The context manager runs the lifespan, which starts the MCP session
    # manager's task group; without it the request 500s.
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
