"""Tests for search.wire — the HTTP boundary models and converters."""

from __future__ import annotations

from store.models import DocumentPage, DocumentSummary
from search.wire import (
    DocumentListResponse,
    DocumentSummaryResponse,
    to_document_list_response,
)


class TestLibraryWireModels:
    """The Library document-list wire models and converter."""

    def test_summary_response_carries_every_field(self) -> None:
        """DocumentSummaryResponse exposes the full document-card payload."""
        model = DocumentSummaryResponse(
            id=7,
            title="Gas Bill",
            correspondent="British Gas",
            document_type="Invoice",
            created="2024-03-01T00:00:00+00:00",
            tags=["utilities", "2024"],
            page_count=2,
        )
        assert model.id == 7
        assert model.page_count == 2
        assert model.tags == ["utilities", "2024"]

    def test_converter_builds_the_paginated_envelope(self) -> None:
        """to_document_list_response maps a DocumentPage to the wire envelope."""
        page = DocumentPage(
            documents=(
                DocumentSummary(
                    id=7,
                    title="Gas Bill",
                    correspondent="British Gas",
                    document_type="Invoice",
                    tags=("utilities",),
                    created="2024-03-01T00:00:00+00:00",
                    page_count=2,
                ),
            ),
            total=41,
            offset=20,
            limit=20,
        )
        response = to_document_list_response(
            page,
            page_number=2,
            page_size=20,
        )
        assert isinstance(response, DocumentListResponse)
        assert response.total == 41
        assert response.page == 2
        assert response.page_size == 20
        assert len(response.documents) == 1
        doc = response.documents[0]
        assert doc.id == 7
        assert doc.title == "Gas Bill"
        assert doc.tags == ["utilities"]
        assert doc.page_count == 2

    def test_converter_handles_an_empty_page(self) -> None:
        """An empty DocumentPage maps to an envelope with no documents."""
        page = DocumentPage(documents=(), total=0, offset=0, limit=20)
        response = to_document_list_response(
            page,
            page_number=1,
            page_size=20,
        )
        assert response.documents == []
        assert response.total == 0
