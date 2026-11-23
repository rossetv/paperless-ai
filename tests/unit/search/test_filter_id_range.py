"""Tests that filter ids outside the SQLite integer range are rejected as input.

Covers the REST search and its stream, the Library listing and the MCP search
tools; the core and store reader are stubbed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from search.appstate import AppState, attach_app_state
from search.deps import get_current_user, require_role
from search.mcp_server import build_mcp_app
from search.offload import LazySemaphore
from search.routes import build_api_router
from search.setup import SetupState
from store import SchemaNotReadyError
from tests.helpers.factories import make_search_settings
from tests.helpers.mcp_client import connect_client
from tests.helpers.search import mint_api_key

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

_OUT_OF_RANGE_FILTERS = [
    {"correspondent_id": _INT64_MAX + 1},
    {"document_type_id": _INT64_MIN - 1},
    {"tag_ids": [1, _INT64_MAX + 1]},
]


def _client(tmp_path: Path, core: MagicMock, store_reader: MagicMock) -> tuple:
    path = str(tmp_path / "app.db")
    conn = connect(path)
    try:
        ensure_schema(conn)
        user = create_user(conn, username="reader", password_hash="h", role="readonly")
        raw_key = mint_api_key(conn, owner_user_id=user.id)
    finally:
        conn.close()
    settings = make_search_settings(APP_DB_PATH=path)
    core.settings = settings
    app = FastAPI()
    attach_app_state(app.state, AppState(app_db_path=path, setup_state=SetupState()))
    app.include_router(
        build_api_router(
            settings,
            lambda _path: core,
            store_reader,
            require_reader=require_role("readonly"),
            require_member=require_role("member"),
            get_current_user=get_current_user,
            search_semaphore=LazySemaphore(4),
            current_settings=lambda: settings,
        )
    )
    client = TestClient(
        app, raise_server_exceptions=False, base_url="https://testserver"
    )
    return client, {"Authorization": f"Bearer {raw_key}"}


@pytest.mark.parametrize("path", ["/api/search", "/api/search/stream"])
@pytest.mark.parametrize("filters", _OUT_OF_RANGE_FILTERS)
def test_search_with_an_out_of_range_filter_id_gets_422(
    tmp_path: Path, path: str, filters: dict[str, Any]
) -> None:
    core = MagicMock()
    client, headers = _client(tmp_path, core, MagicMock())

    response = client.post(
        path, json={"query": "gas bill", "filters": filters}, headers=headers
    )

    assert response.status_code == 422
    core.answer.assert_not_called()


@pytest.mark.parametrize(
    "params",
    [
        {"correspondent_id": _INT64_MAX + 1},
        {"document_type_id": _INT64_MIN - 1},
        {"tag_ids": [1, _INT64_MAX + 1]},
    ],
)
def test_library_with_an_out_of_range_filter_id_gets_422(
    tmp_path: Path, params: dict[str, Any]
) -> None:
    store_reader = MagicMock()
    client, headers = _client(tmp_path, MagicMock(), store_reader)

    response = client.get("/api/documents", params=params, headers=headers)

    assert response.status_code == 422
    store_reader.list_documents.assert_not_called()


def test_library_passes_filter_ids_at_the_range_edges_to_the_reader(
    tmp_path: Path,
) -> None:
    store_reader = MagicMock()
    store_reader.list_documents.side_effect = SchemaNotReadyError("no index")
    client, headers = _client(tmp_path, MagicMock(), store_reader)

    response = client.get(
        "/api/documents",
        params={
            "correspondent_id": _INT64_MIN,
            "document_type_id": _INT64_MAX,
            "tag_ids": [_INT64_MIN, _INT64_MAX],
        },
        headers=headers,
    )

    assert response.status_code == 503
    query = store_reader.list_documents.call_args.args[0]
    assert query.correspondent_id == _INT64_MIN
    assert query.document_type_id == _INT64_MAX
    assert tuple(query.tag_ids) == (_INT64_MIN, _INT64_MAX)


def _mcp_core() -> MagicMock:
    core = MagicMock()
    core.settings = make_search_settings()
    return core


@pytest.mark.anyio
@pytest.mark.parametrize("filters", _OUT_OF_RANGE_FILTERS)
async def test_mcp_keyword_search_rejects_an_out_of_range_filter_id(
    filters: dict[str, Any],
) -> None:
    core = _mcp_core()
    app = build_mcp_app(lambda _p: core, "unused", search_semaphore=LazySemaphore(0))

    async with connect_client(app._server) as client:
        result = await client.call_tool("keyword_search", {"filters": filters})

    assert result.isError is True
    assert next(iter(filters)) in result.content[0].text
    core.keyword_search.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["semantic_search", "deep_search"])
async def test_mcp_search_tools_reject_an_out_of_range_filter_id(tool: str) -> None:
    core = _mcp_core()
    app = build_mcp_app(lambda _p: core, "unused", search_semaphore=LazySemaphore(0))
    query_arg = "question" if tool == "deep_search" else "query"

    async with connect_client(app._server) as client:
        result = await client.call_tool(
            tool,
            {query_arg: "gas bill", "filters": {"correspondent_id": _INT64_MAX + 1}},
        )

    assert result.isError is True
    assert "correspondent_id" in result.content[0].text
    core.answer.assert_not_called()
    core.retrieve.assert_not_called()
