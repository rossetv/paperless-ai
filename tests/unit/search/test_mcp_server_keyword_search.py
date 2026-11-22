"""Tests for the keyword_search MCP tool.

Driven through the in-memory MCP transport with a stubbed core.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from search.mcp_server import build_mcp_app
from search.offload import LazySemaphore
from store.models import DocumentSummary, KeywordHit, KeywordPage
from tests.helpers.factories import make_search_settings


def _summary(doc_id: int = 42) -> DocumentSummary:
    return DocumentSummary(
        id=doc_id,
        title="Invoice 2024",
        correspondent="Acme",
        document_type="Invoice",
        tags=("tax",),
        created="2024-01-01T00:00:00+00:00",
        page_count=2,
    )


def _make_core(page: KeywordPage | None = None) -> MagicMock:
    core = MagicMock()
    core.keyword_search.return_value = page or KeywordPage(
        hits=(KeywordHit(document=_summary(), snippet="an invoice total", rank=-1.2),),
        total=1,
        offset=0,
        limit=20,
    )
    core.settings = make_search_settings()
    return core


def _build_app(core: MagicMock):
    return build_mcp_app(
        lambda _app_db_path: core,
        "unused-app-db-path",
        search_semaphore=LazySemaphore(0),
    )


@pytest.mark.anyio
async def test_keyword_search_returns_document_list_with_urls() -> None:
    from tests.helpers.mcp_client import connect_client

    core = _make_core()
    app = _build_app(core)

    async with connect_client(app._server) as client:
        result = await client.call_tool("keyword_search", {"query": "invoice"})

    payload = json.loads(result.content[0].text)
    assert payload["total"] == 1
    doc = payload["documents"][0]
    assert doc["document_id"] == 42
    assert doc["title"] == "Invoice 2024"
    assert doc["snippet"] == "an invoice total"
    assert doc["paperless_url"].endswith("/documents/42/")


@pytest.mark.anyio
async def test_keyword_search_clamps_limit_and_passes_filters() -> None:
    from tests.helpers.mcp_client import connect_client

    core = _make_core()
    app = _build_app(core)

    async with connect_client(app._server) as client:
        await client.call_tool(
            "keyword_search",
            {
                "query": "report",
                "filters": {"correspondent_id": 10, "tag_ids": [101]},
                "limit": 999,
                "offset": 5,
            },
        )

    core.keyword_search.assert_called_once()
    args = core.keyword_search.call_args.args
    # signature: (query, ui_filters, limit, offset)
    assert args[0] == "report"
    ui_filters = args[1]
    assert ui_filters.correspondent_id == 10
    assert tuple(ui_filters.tag_ids) == (101,)
    assert args[2] == 50  # limit clamped to the max
    assert args[3] == 5


@pytest.mark.anyio
async def test_keyword_search_filter_only_browse_passes_none_query() -> None:
    from tests.helpers.mcp_client import connect_client

    core = _make_core(
        page=KeywordPage(
            hits=(KeywordHit(document=_summary(7), snippet=None, rank=0.0),),
            total=1,
            offset=0,
            limit=20,
        )
    )
    app = _build_app(core)

    async with connect_client(app._server) as client:
        result = await client.call_tool(
            "keyword_search", {"filters": {"tag_ids": [101]}}
        )

    core.keyword_search.assert_called_once()
    assert core.keyword_search.call_args.args[0] is None
    payload = json.loads(result.content[0].text)
    assert payload["documents"][0]["snippet"] is None


@pytest.mark.anyio
async def test_keyword_search_sanitises_failure() -> None:
    from tests.helpers.mcp_client import connect_client

    core = _make_core()
    core.keyword_search.side_effect = RuntimeError(
        "sqlite3 error at /var/data/paperless/index.db"
    )
    app = _build_app(core)

    async with connect_client(app._server) as client:
        result = await client.call_tool("keyword_search", {"query": "x"})

    assert result.isError is True
    error_text = " ".join(b.text for b in result.content if hasattr(b, "text"))
    assert "/var/data/paperless/index.db" not in error_text


@pytest.mark.anyio
async def test_keyword_search_rejects_an_over_length_query() -> None:
    from tests.helpers.mcp_client import connect_client

    from search.wire import MAX_QUERY_LENGTH

    core = _make_core()
    app = _build_app(core)

    async with connect_client(app._server) as client:
        result = await client.call_tool(
            "keyword_search", {"query": "x" * (MAX_QUERY_LENGTH + 1)}
        )

    assert result.isError is True
    assert str(MAX_QUERY_LENGTH) in result.content[0].text
    core.keyword_search.assert_not_called()


@pytest.mark.anyio
async def test_keyword_search_accepts_a_query_at_the_length_limit() -> None:
    from tests.helpers.mcp_client import connect_client

    from search.wire import MAX_QUERY_LENGTH

    core = _make_core()
    app = _build_app(core)

    async with connect_client(app._server) as client:
        result = await client.call_tool(
            "keyword_search", {"query": "x" * MAX_QUERY_LENGTH}
        )

    assert result.isError is False
    core.keyword_search.assert_called_once()


@pytest.mark.anyio
async def test_keyword_search_invalid_filter_tells_the_caller_which_field() -> None:
    from tests.helpers.mcp_client import connect_client

    core = _make_core()
    app = _build_app(core)

    async with connect_client(app._server) as client:
        result = await client.call_tool(
            "keyword_search", {"filters": {"tag_ids": "not-a-list"}}
        )

    assert result.isError is True
    assert "tag_ids" in result.content[0].text
    core.keyword_search.assert_not_called()
