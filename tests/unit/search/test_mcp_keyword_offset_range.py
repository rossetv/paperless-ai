"""The MCP keyword search refuses an offset SQLite cannot bind."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from search.mcp_server import build_mcp_app
from search.offload import LazySemaphore
from tests.helpers.factories import make_search_settings
from tests.helpers.mcp_client import connect_client


@pytest.mark.anyio
@pytest.mark.parametrize("offset", [2**63, 2**80])
async def test_mcp_keyword_search_refuses_an_offset_beyond_the_integer_range(
    offset: int,
) -> None:
    core = MagicMock()
    core.settings = make_search_settings()
    app = build_mcp_app(lambda _p: core, "unused", search_semaphore=LazySemaphore(0))

    async with connect_client(app._server) as client:
        result = await client.call_tool("keyword_search", {"offset": offset})

    assert result.isError is True
    assert "offset" in result.content[0].text
    core.keyword_search.assert_not_called()


@pytest.mark.anyio
async def test_mcp_keyword_search_passes_the_largest_offset_through() -> None:
    core = MagicMock()
    core.settings = make_search_settings()
    core.keyword_search.return_value = MagicMock(
        hits=[], total=0, offset=2**63 - 1, limit=20
    )
    app = build_mcp_app(lambda _p: core, "unused", search_semaphore=LazySemaphore(0))

    async with connect_client(app._server) as client:
        result = await client.call_tool("keyword_search", {"offset": 2**63 - 1})

    assert result.isError is not True
    assert core.keyword_search.call_args.args[3] == 2**63 - 1
