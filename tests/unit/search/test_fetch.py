"""Tests for search.fetch.assemble_fetched — full-document fetch assembly.

Covers the spec §4.3 contract with a stub Paperless client and store reader:
- happy path returns capped content + wrapper metadata + deep-link;
- content over the cap is truncated and flagged with total/returned lengths;
- a 404 (unknown/deleted id) becomes a per-id "not found", not an exception;
- any other Paperless fault becomes a sanitised "fetch failed";
- a per-id failure never aborts the rest of the batch;
- metadata falls back to the Paperless response when the index has no row.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from search.fetch import assemble_fetched
from store.models import DocumentSummary


def _summary(doc_id: int, title: str, pages: int) -> DocumentSummary:
    return DocumentSummary(
        id=doc_id,
        title=title,
        correspondent=None,
        document_type=None,
        tags=(),
        created=None,
        page_count=pages,
    )


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://paperless.invalid/api/documents/9/")
    response = httpx.Response(status_code=status, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


class _StubClient:
    """Returns scripted docs by id; raises the scripted error otherwise."""

    def __init__(
        self, docs: dict[int, dict], errors: dict[int, Exception] | None = None
    ):
        self._docs = docs
        self._errors = errors or {}

    def get_document(self, doc_id: int) -> dict:
        if doc_id in self._errors:
            raise self._errors[doc_id]
        if doc_id not in self._docs:
            raise _http_error(404)
        return self._docs[doc_id]


def _reader(summaries: dict[int, DocumentSummary]) -> MagicMock:
    reader = MagicMock()
    reader.get_document_summary.side_effect = lambda doc_id: summaries.get(doc_id)
    return reader


def test_assemble_fetched_happy_path() -> None:
    client = _StubClient(
        {1: {"content": "the full text", "title": "X", "page_count": 3}}
    )
    reader = _reader({1: _summary(1, "Indexed Title", 3)})

    [doc] = assemble_fetched([1], client, reader, "http://p", max_chars=50000)

    assert doc.error is None
    assert doc.content == "the full text"
    assert doc.truncated is False
    assert doc.total_chars == len("the full text")
    assert doc.returned_chars == len("the full text")
    assert doc.title == "Indexed Title"  # local index preferred
    assert doc.page_count == 3
    assert doc.paperless_url == "http://p/documents/1/"


def test_assemble_fetched_truncates_and_flags() -> None:
    client = _StubClient({1: {"content": "x" * 60000}})
    reader = _reader({1: _summary(1, "T", 9)})

    [doc] = assemble_fetched([1], client, reader, "http://p", max_chars=50000)

    assert doc.truncated is True
    assert doc.total_chars == 60000
    assert doc.returned_chars == 50000
    assert len(doc.content) == 50000


def test_assemble_fetched_unknown_id_is_per_id_error() -> None:
    client = _StubClient({})  # any id → 404
    reader = _reader({})

    [doc] = assemble_fetched([9], client, reader, "http://p", max_chars=50000)

    assert doc.error == "not found"
    assert doc.content == ""
    assert doc.paperless_url == "http://p/documents/9/"


def test_assemble_fetched_other_fault_is_sanitised() -> None:
    client = _StubClient({}, errors={5: _http_error(500)})
    reader = _reader({})

    [doc] = assemble_fetched([5], client, reader, "http://p", max_chars=50000)

    assert doc.error == "fetch failed"
    assert doc.content == ""


def test_assemble_fetched_one_bad_id_does_not_fail_batch() -> None:
    client = _StubClient({1: {"content": "ok"}})  # id 2 → 404
    reader = _reader({1: _summary(1, "Doc 1", 1)})

    results = assemble_fetched([1, 2], client, reader, "http://p", max_chars=50000)

    assert [r.document_id for r in results] == [1, 2]
    assert results[0].error is None and results[0].content == "ok"
    assert results[1].error == "not found"


def test_assemble_fetched_falls_back_to_paperless_metadata() -> None:
    client = _StubClient({7: {"content": "body", "title": "From PL", "page_count": 4}})
    reader = _reader({})  # not in the local index

    [doc] = assemble_fetched([7], client, reader, "http://p", max_chars=50000)

    assert doc.title == "From PL"
    assert doc.page_count == 4
