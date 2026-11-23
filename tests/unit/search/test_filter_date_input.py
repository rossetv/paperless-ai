"""Filter dates that cannot be read are refused as input, not dropped."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from search.mcp_server import build_mcp_app
from search.offload import LazySemaphore
from store import SchemaNotReadyError
from tests.helpers.factories import make_search_settings
from tests.helpers.mcp_client import connect_client
from tests.unit.search.test_filter_id_range import _client

_BAD_DATES = ["2024-13-45", "yesterday", "2024-02-30", "2024-1-1"]
_GOOD_DATES = ["2024-02-29", "2024-02-29T10:00:00+00:00", "2024-W09-4", ""]


@pytest.mark.parametrize("field", ["date_from", "date_to"])
@pytest.mark.parametrize("bad", _BAD_DATES)
@pytest.mark.parametrize("path", ["/api/search", "/api/search/stream"])
def test_search_with_an_unreadable_date_gets_422(
    tmp_path: Path, path: str, bad: str, field: str
) -> None:
    core = MagicMock()
    client, headers = _client(tmp_path, core, MagicMock())

    response = client.post(
        path, json={"query": "gas bill", "filters": {field: bad}}, headers=headers
    )

    assert response.status_code == 422
    assert field in response.text
    core.answer.assert_not_called()


@pytest.mark.parametrize("field", ["date_from", "date_to"])
@pytest.mark.parametrize("bad", _BAD_DATES)
def test_library_with_an_unreadable_date_gets_422(
    tmp_path: Path, bad: str, field: str
) -> None:
    store_reader = MagicMock()
    client, headers = _client(tmp_path, MagicMock(), store_reader)

    response = client.get("/api/documents", params={field: bad}, headers=headers)

    assert response.status_code == 422
    store_reader.list_documents.assert_not_called()


@pytest.mark.parametrize("good", _GOOD_DATES)
def test_library_still_accepts_every_readable_date_form(
    tmp_path: Path, good: str
) -> None:
    store_reader = MagicMock()
    store_reader.list_documents.side_effect = SchemaNotReadyError("no index")
    client, headers = _client(tmp_path, MagicMock(), store_reader)

    response = client.get(
        "/api/documents", params={"date_from": good, "date_to": good}, headers=headers
    )

    assert response.status_code == 503
    store_reader.list_documents.assert_called_once()


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["semantic_search", "deep_search", "keyword_search"])
@pytest.mark.parametrize("field", ["date_from", "date_to"])
async def test_mcp_search_tools_reject_an_unreadable_date(
    tool: str, field: str
) -> None:
    core = MagicMock()
    core.settings = make_search_settings()
    app = build_mcp_app(lambda _p: core, "unused", search_semaphore=LazySemaphore(0))
    args: dict = {"filters": {field: "2024-13-45"}}
    if tool != "keyword_search":
        args["question" if tool == "deep_search" else "query"] = "gas bill"

    async with connect_client(app._server) as client:
        result = await client.call_tool(tool, args)

    assert result.isError is True
    assert field in result.content[0].text
    core.answer.assert_not_called()
    core.retrieve.assert_not_called()
    core.keyword_search.assert_not_called()


@pytest.mark.anyio
async def test_mcp_keyword_search_accepts_a_timestamp_date() -> None:
    core = MagicMock()
    core.settings = make_search_settings()
    core.keyword_search.return_value = MagicMock(hits=[], total=0, offset=0, limit=20)
    app = build_mcp_app(lambda _p: core, "unused", search_semaphore=LazySemaphore(0))

    async with connect_client(app._server) as client:
        result = await client.call_tool(
            "keyword_search",
            {"filters": {"date_from": "2024-01-01T00:00:00+00:00", "date_to": ""}},
        )

    assert result.isError is not True
    ui_filters = core.keyword_search.call_args.args[1]
    assert ui_filters.date_from == "2024-01-01"
    assert ui_filters.date_to is None
