"""An in-process MCP client for the tool tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from mcp import Client
from mcp.server.mcpserver import MCPServer


class _ToolClient:
    """Calls tools on a connected :class:`mcp.Client`.

    A call result keeps the wire's field names (``isError``, ``content``,
    ``structuredContent``), as the MCP client shows them.
    """

    def __init__(self, client: Client) -> None:
        self._client = client

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> SimpleNamespace:
        result = await self._client.call_tool(name, arguments)
        return SimpleNamespace(
            isError=result.is_error,
            content=result.content,
            structuredContent=result.structured_content,
        )

    async def list_tools(self) -> Any:
        return await self._client.list_tools()


@asynccontextmanager
async def connect_client(server: MCPServer) -> AsyncIterator[_ToolClient]:
    """Connect a client to *server* in process, with the initialize handshake."""
    async with Client(server, mode="legacy") as client:
        yield _ToolClient(client)
