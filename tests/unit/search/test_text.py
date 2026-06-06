"""Tests for search.text helpers, incl. the RAG-08 trivial-query predicate."""

from __future__ import annotations

import pytest

from search.text import is_trivial_query


class TestIsTrivialQuery:
    """A query is trivial only when short AND free of temporal/entity signal."""

    @pytest.mark.parametrize(
        "query",
        ["invoices", "boiler warranty", "tax documents", "council tax"],
    )
    def test_short_plain_queries_are_trivial(self, query: str) -> None:
        assert is_trivial_query(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "invoices from last year",  # relative-date word
            "documents since March",  # month name
            "council tax 2024",  # digit
            "letters from npower Limited",  # too long + proper noun
            "what did I pay British Gas in January",  # long + month + proper noun
            "invoice #4501",  # identifier punctuation
            "energy bills for the past six months",  # long + temporal
        ],
    )
    def test_temporal_or_entity_or_long_queries_are_not_trivial(
        self, query: str
    ) -> None:
        assert is_trivial_query(query) is False

    def test_empty_query_is_not_trivial(self) -> None:
        assert is_trivial_query("") is False
        assert is_trivial_query("   ") is False
