"""Tests for the fetch_documents MCP tool.

fetch_documents is a zero-LLM tool that fetches full OCR text live from Paperless
through an injected per-request client. These tests drive it via the in-memory
MCP transport with a stub paperless_factory, asserting: boundary validation
(empty / >5 ids), the truncation flag, per-id "not found" for an unknown id, and
that the per-request client is closed after use.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from search.core import SearchCore
from search.mcp_server import build_mcp_app as _real_build_mcp_app
from search.offload import LazySemaphore
from store.models import DocumentSummary
from tests.helpers.factories import make_search_settings


def _http_404() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://paperless.invalid/api/documents/9/")
    return httpx.HTTPStatusError(
        "404", request=request, response=httpx.Response(404, request=request)
    )


class _StubClient:
    def __init__(self, docs: dict[int, dict]) -> None:
        self._docs = docs
        self.closed = False

    def get_document(self, doc_id: int) -> dict:
        if doc_id not in self._docs:
            raise _http_404()
        return self._docs[doc_id]

    def close(self) -> None:
        self.closed = True


def _make_core(docs: dict[int, dict]) -> tuple[MagicMock, _StubClient]:
    """A real-ish core that delegates to the real SearchCore.fetch_documents.

    We stub the store reader's get_document_summary and the Paperless client; the
    assembly logic under test is the real core/fetch code path.
    """
    client = _StubClient(docs)
    core = MagicMock(spec=SearchCore)
    core.settings = make_search_settings()

    reader = MagicMock()
    reader.get_document_summary.side_effect = lambda doc_id: DocumentSummary(
        id=doc_id,
        title=f"Doc {doc_id}",
        correspondent=None,
        document_type=None,
        tags=(),
        created=None,
        page_count=1,
    )
    # Drive the real fetch_documents via a lightweight bound delegate.
    from search.fetch import assemble_fetched

    core.fetch_documents.side_effect = lambda ids, c: assemble_fetched(
        ids, c, reader, core.settings.PAPERLESS_PUBLIC_URL, 50_000
    )
    return core, client


def _build_app(core: MagicMock, client: _StubClient):
    return _real_build_mcp_app(
        lambda _app_db_path: core,
        "unused-app-db-path",
        search_semaphore=LazySemaphore(0),
        paperless_factory=lambda _settings: client,
    )


@pytest.mark.anyio
async def test_fetch_documents_returns_content_and_closes_client() -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    core, client = _make_core({1: {"content": "the whole document text"}})
    app = _build_app(core, client)

    async with create_connected_server_and_client_session(app._fastmcp) as session:
        result = await session.call_tool("fetch_documents", {"document_ids": [1]})

    payload = json.loads(result.content[0].text)
    doc = payload["documents"][0]
    assert doc["document_id"] == 1
    assert doc["content"] == "the whole document text"
    assert doc["truncated"] is False
    assert doc["error"] is None
    assert client.closed is True


@pytest.mark.anyio
async def test_fetch_documents_truncates_large_content() -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    core, client = _make_core({1: {"content": "x" * 60000}})
    app = _build_app(core, client)

    async with create_connected_server_and_client_session(app._fastmcp) as session:
        result = await session.call_tool("fetch_documents", {"document_ids": [1]})

    doc = json.loads(result.content[0].text)["documents"][0]
    assert doc["truncated"] is True
    assert doc["total_chars"] == 60000
    assert doc["returned_chars"] == 50000


@pytest.mark.anyio
async def test_fetch_documents_unknown_id_is_per_id_error() -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    core, client = _make_core({})  # any id → 404
    app = _build_app(core, client)

    async with create_connected_server_and_client_session(app._fastmcp) as session:
        result = await session.call_tool("fetch_documents", {"document_ids": [9]})

    doc = json.loads(result.content[0].text)["documents"][0]
    assert doc["error"] == "not found"
    assert doc["content"] == ""


@pytest.mark.anyio
async def test_fetch_documents_rejects_too_many_ids() -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    core, client = _make_core({})
    app = _build_app(core, client)

    async with create_connected_server_and_client_session(app._fastmcp) as session:
        result = await session.call_tool(
            "fetch_documents", {"document_ids": [1, 2, 3, 4, 5, 6]}
        )

    assert result.isError is True
    core.fetch_documents.assert_not_called()


@pytest.mark.anyio
async def test_fetch_documents_rejects_empty_ids() -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    core, client = _make_core({})
    app = _build_app(core, client)

    async with create_connected_server_and_client_session(app._fastmcp) as session:
        result = await session.call_tool("fetch_documents", {"document_ids": []})

    assert result.isError is True
    core.fetch_documents.assert_not_called()
