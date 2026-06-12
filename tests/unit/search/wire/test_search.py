"""Tests for the search wire models in search.wire.search.

Covers: SearchRequest enforces the query length bounds at the HTTP boundary —
an empty or whitespace-only query is rejected with a ValidationError (HTTP-04,
§10.4/§10.6), so it never reaches the bounded LLM pipeline and burns budget;
a query over the maximum length is rejected; a valid query is trimmed of
surrounding whitespace so the pipeline sees one normalised form (HTTP-07).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from search.wire import MAX_QUERY_LENGTH, FilterRequest, SearchRequest


def test_search_request_accepts_a_normal_query() -> None:
    """A non-empty query within bounds validates and is preserved."""
    request = SearchRequest(query="what is my gas bill total")
    assert request.query == "what is my gas bill total"


def test_search_request_rejects_an_empty_query() -> None:
    """An empty query is rejected at the boundary, never dispatched to the LLM."""
    with pytest.raises(ValidationError):
        SearchRequest(query="")


def test_search_request_rejects_a_whitespace_only_query() -> None:
    """A whitespace-only query is rejected — it is empty after trimming."""
    with pytest.raises(ValidationError):
        SearchRequest(query="   \t\n  ")


def test_search_request_trims_surrounding_whitespace() -> None:
    """A valid query is trimmed so the pipeline sees one normalised form."""
    request = SearchRequest(query="  invoices from acme  ")
    assert request.query == "invoices from acme"


def test_search_request_rejects_a_query_over_the_maximum_length() -> None:
    """A query longer than MAX_QUERY_LENGTH is rejected at the boundary."""
    with pytest.raises(ValidationError):
        SearchRequest(query="x" * (MAX_QUERY_LENGTH + 1))


def test_search_request_accepts_a_query_at_the_maximum_length() -> None:
    """A query of exactly MAX_QUERY_LENGTH characters validates."""
    request = SearchRequest(query="x" * MAX_QUERY_LENGTH)
    assert len(request.query) == MAX_QUERY_LENGTH


def test_filter_request_accepts_up_to_64_tag_ids() -> None:
    """A filter naming up to 64 tags validates (L16)."""
    filters = FilterRequest(tag_ids=list(range(64)))
    assert len(filters.tag_ids) == 64


def test_filter_request_rejects_over_64_tag_ids() -> None:
    """A filter naming more than 64 tags is rejected, matching the GET bound (L16)."""
    with pytest.raises(ValidationError):
        FilterRequest(tag_ids=list(range(65)))
