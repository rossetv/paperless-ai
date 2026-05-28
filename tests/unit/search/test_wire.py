"""Tests for search.wire — the HTTP boundary models and converters."""

from __future__ import annotations

from store.models import DocumentPage, DocumentSummary
from search.wire import (
    DocumentListResponse,
    DocumentSummaryResponse,
    to_document_list_response,
    to_document_summary_response,
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
            paperless_url="https://paperless.example/documents/7/",
        )
        assert model.id == 7
        assert model.page_count == 2
        assert model.tags == ["utilities", "2024"]
        assert model.paperless_url == "https://paperless.example/documents/7/"

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
            paperless_base_url="https://p.example",
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
        assert doc.paperless_url == "https://p.example/documents/7/"

    def test_to_document_summary_response_copies_all_fields(self) -> None:
        """to_document_summary_response maps every field from the store dataclass."""
        summary = DocumentSummary(
            id=42,
            title="An invoice",
            correspondent="ACME",
            document_type="Invoice",
            tags=("urgent", "2024"),
            created="2024-03-01T00:00:00Z",
            page_count=3,
        )

        response = to_document_summary_response(
            summary, paperless_url="https://p.example/documents/42/"
        )

        assert response.id == 42
        assert response.title == "An invoice"
        assert response.correspondent == "ACME"
        assert response.document_type == "Invoice"
        assert response.created == "2024-03-01T00:00:00Z"
        assert response.tags == ["urgent", "2024"]
        assert response.page_count == 3

    def test_to_document_summary_response_includes_paperless_url(self) -> None:
        """to_document_summary_response forwards the supplied paperless_url."""
        summary = DocumentSummary(
            id=42,
            title="An invoice",
            correspondent="ACME",
            document_type="Invoice",
            tags=("urgent",),
            created="2024-03-01T00:00:00Z",
            page_count=3,
        )
        response = to_document_summary_response(
            summary, paperless_url="https://p.example/documents/42/"
        )
        assert response.paperless_url == "https://p.example/documents/42/"

    def test_converter_handles_an_empty_page(self) -> None:
        """An empty DocumentPage maps to an envelope with no documents."""
        page = DocumentPage(documents=(), total=0, offset=0, limit=20)
        response = to_document_list_response(
            page,
            page_number=1,
            page_size=20,
            paperless_base_url="https://p.example",
        )
        assert response.documents == []
        assert response.total == 0


class TestBrowseQueryParser:
    """to_document_browse_query maps validated HTTP params to the store shape."""

    def test_defaults_produce_a_first_page_descending_by_added(self) -> None:
        """With only page/page_size, the query defaults sensibly."""
        from search.wire import to_document_browse_query

        query = to_document_browse_query(
            page=1,
            page_size=20,
            sort="added",
            descending=True,
            text=None,
            date_from=None,
            date_to=None,
            correspondent_id=None,
            document_type_id=None,
            tag_ids=[],
        )
        assert query.offset == 0
        assert query.limit == 20
        assert query.sort == "indexed_at"
        assert query.descending is True
        assert query.tag_ids == ()

    def test_page_two_offsets_by_one_page_size(self) -> None:
        """offset is (page - 1) * page_size."""
        from search.wire import to_document_browse_query

        query = to_document_browse_query(
            page=3,
            page_size=25,
            sort="created",
            descending=True,
            text=None,
            date_from=None,
            date_to=None,
            correspondent_id=None,
            document_type_id=None,
            tag_ids=[],
        )
        assert query.offset == 50
        assert query.limit == 25

    def test_added_sort_maps_to_indexed_at(self) -> None:
        """The public 'added' sort name maps to the store's indexed_at column."""
        from search.wire import to_document_browse_query

        query = to_document_browse_query(
            page=1,
            page_size=20,
            sort="added",
            descending=False,
            text=None,
            date_from=None,
            date_to=None,
            correspondent_id=None,
            document_type_id=None,
            tag_ids=[],
        )
        assert query.sort == "indexed_at"

    def test_created_and_title_sorts_pass_through(self) -> None:
        """created and title are passed to the store unchanged."""
        from search.wire import to_document_browse_query

        for public_sort in ("created", "title"):
            query = to_document_browse_query(
                page=1,
                page_size=20,
                sort=public_sort,
                descending=True,
                text=None,
                date_from=None,
                date_to=None,
                correspondent_id=None,
                document_type_id=None,
                tag_ids=[],
            )
            assert query.sort == public_sort

    def test_unknown_sort_raises_value_error(self) -> None:
        """An unrecognised sort name is rejected with ValueError."""
        import pytest

        from search.wire import to_document_browse_query

        with pytest.raises(ValueError, match="sort"):
            to_document_browse_query(
                page=1,
                page_size=20,
                sort="relevance",
                descending=True,
                text=None,
                date_from=None,
                date_to=None,
                correspondent_id=None,
                document_type_id=None,
                tag_ids=[],
            )

    def test_filters_and_text_are_carried_through(self) -> None:
        """Every filter and the text query reach the store shape."""
        from search.wire import to_document_browse_query

        query = to_document_browse_query(
            page=1,
            page_size=20,
            sort="created",
            descending=True,
            text="gas bill",
            date_from="2024-01-01",
            date_to="2024-12-31",
            correspondent_id=10,
            document_type_id=20,
            tag_ids=[101, 102],
        )
        assert query.text == "gas bill"
        assert query.date_from == "2024-01-01"
        assert query.date_to == "2024-12-31"
        assert query.correspondent_id == 10
        assert query.document_type_id == 20
        assert query.tag_ids == (101, 102)
