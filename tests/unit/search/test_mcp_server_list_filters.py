"""Tests for the list_filters MCP tool.

list_filters is a zero-LLM tool: it returns the filter catalogue (correspondents,
document types, tags — each with a count — plus the date range) from the local
index so a calling model can discover valid filter ids. These tests drive it via
the in-memory MCP transport.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from search.mcp_server import build_mcp_app
from search.offload import LazySemaphore
from store.models import FilterCatalog, FilterFacet
from tests.helpers.factories import make_search_settings


def _catalog() -> FilterCatalog:
    return FilterCatalog(
        correspondents=(FilterFacet(id=10, name="Acme", count=2),),
        document_types=(FilterFacet(id=20, name="Invoice", count=5),),
        tags=(
            FilterFacet(id=101, name="tax", count=3),
            FilterFacet(id=102, name="scanned", count=7),
        ),
        earliest="2023-01-01T00:00:00+00:00",
        latest="2024-06-15T00:00:00+00:00",
    )


def _make_core() -> MagicMock:
    core = MagicMock()
    core.list_filters.return_value = _catalog()
    core.settings = make_search_settings()
    return core


def _build_app(core: MagicMock):
    return build_mcp_app(
        lambda _app_db_path: core,
        "unused-app-db-path",
        search_semaphore=LazySemaphore(0),
    )


@pytest.mark.anyio
async def test_list_filters_returns_catalog_with_counts() -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    core = _make_core()
    app = _build_app(core)

    async with create_connected_server_and_client_session(app._fastmcp) as client:
        result = await client.call_tool("list_filters", {})

    core.list_filters.assert_called_once()
    payload = json.loads(result.content[0].text)
    assert payload["correspondents"] == [{"id": 10, "name": "Acme", "count": 2}]
    assert payload["document_types"] == [{"id": 20, "name": "Invoice", "count": 5}]
    assert {"id": 101, "name": "tax", "count": 3} in payload["tags"]
    assert payload["date_range"] == {
        "earliest": "2023-01-01T00:00:00+00:00",
        "latest": "2024-06-15T00:00:00+00:00",
    }


@pytest.mark.anyio
async def test_list_filters_sanitises_store_failure() -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    core = _make_core()
    core.list_filters.side_effect = RuntimeError(
        "sqlite3 error opening /var/data/paperless/index.db"
    )
    app = _build_app(core)

    async with create_connected_server_and_client_session(app._fastmcp) as client:
        result = await client.call_tool("list_filters", {})

    assert result.isError is True
    error_text = " ".join(b.text for b in result.content if hasattr(b, "text"))
    assert "/var/data/paperless/index.db" not in error_text
