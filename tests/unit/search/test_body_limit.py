"""Tests for the request-body size limit and the bounded request lists."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from search.body_limit import MAX_BODY_BYTES, BodyLimitMiddleware
from search.wire import CreateApiKeyRequest, DocumentPatchRequest, UpdateApiKeyRequest
from tests.helpers.factories import make_search_settings
from tests.unit.search.conftest import build_test_client


def test_oversized_body_gets_413_before_auth_with_security_headers() -> None:
    client = build_test_client(make_search_settings())
    response = client.post("/api/search", content=b"x" * (MAX_BODY_BYTES + 1))
    assert response.status_code == 413
    assert "detail" in response.json()
    assert response.headers["x-content-type-options"] == "nosniff"


def test_body_within_the_limit_still_reaches_auth() -> None:
    client = build_test_client(make_search_settings())
    response = client.post("/api/search", json={"query": "hello"})
    assert response.status_code == 401


def test_oversized_mcp_body_gets_413() -> None:
    client = build_test_client(make_search_settings())
    response = client.post("/mcp", content=b"x" * (MAX_BODY_BYTES + 1))
    assert response.status_code == 413


async def _drive(
    chunks: list[bytes], *, headers: list[tuple[bytes, bytes]] | None = None
) -> tuple[list[dict], list[bytes]]:
    """Run the middleware over an echo app; return (sent messages, bodies the app read)."""
    seen: list[bytes] = []

    async def app(scope, receive, send) -> None:
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return
            seen.append(message["body"])
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    queue = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]
    sent: list[dict] = []

    async def receive() -> dict:
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {"type": "http", "headers": headers or []}
    await BodyLimitMiddleware(app, max_bytes=10)(scope, receive, send)
    return sent, seen


def test_streamed_body_without_a_length_is_cut_off_with_413() -> None:
    sent, seen = asyncio.run(_drive([b"123456", b"123456", b"123456"]))
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["detail"]
    assert len(sent) == 2  # nothing the app says afterwards leaks out
    assert len(seen) == 1  # reading stopped at the chunk that crossed the limit


def test_consecutive_413s_carry_identical_headers_without_duplicates() -> None:
    def refused_headers() -> list[tuple[bytes, bytes]]:
        sent: list[dict] = []

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                message["headers"].append((b"x-frame-options", b"DENY"))
            sent.append(message)

        async def receive() -> dict:
            return {"type": "http.disconnect"}

        scope = {"type": "http", "headers": [(b"content-length", b"11")]}

        async def run() -> None:
            await BodyLimitMiddleware(None, max_bytes=10)(scope, receive, send)  # type: ignore[arg-type]

        asyncio.run(run())
        return sent[0]["headers"]

    first, second = refused_headers(), refused_headers()
    assert first == second
    assert len(second) == len(set(second))


def test_streamed_body_within_the_limit_passes_through() -> None:
    sent, _ = asyncio.run(_drive([b"12345", b"12345"]))
    assert sent[0]["status"] == 200


def test_a_false_content_length_does_not_hide_a_large_body() -> None:
    sent, _ = asyncio.run(
        _drive([b"1234567890123"], headers=[(b"content-length", b"3")])
    )
    assert sent[0]["status"] == 413


def test_document_patch_tags_are_bounded() -> None:
    DocumentPatchRequest(tags=list(range(1000)))
    with pytest.raises(ValidationError):
        DocumentPatchRequest(tags=list(range(1001)))


def test_api_key_scopes_are_bounded() -> None:
    too_many = ["api"] * 65
    with pytest.raises(ValidationError):
        CreateApiKeyRequest(name="k", scopes=too_many)
    with pytest.raises(ValidationError):
        UpdateApiKeyRequest(scopes=too_many)
