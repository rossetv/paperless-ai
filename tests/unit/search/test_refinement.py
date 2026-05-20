"""Tests for src/search/refinement.py.

Verifies the contract of both pure helpers:
- broaden_plan: drops filter candidates, preserves the rest.
- adjust_plan: incorporates an adjustment hint, preserves the original content.
Both must return new QueryPlan instances without mutating the input.
"""

from __future__ import annotations

import pytest

from search.models import FilterCandidates, QueryPlan
from search.refinement import adjust_plan, broaden_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_filter_candidates(
    correspondent: str | None = "npower",
    document_type: str | None = "invoice",
    tags: tuple[str, ...] = ("electricity",),
    date_from: str | None = "2024-01-01",
    date_to: str | None = "2024-12-31",
) -> FilterCandidates:
    return FilterCandidates(
        correspondent=correspondent,
        document_type=document_type,
        tags=tags,
        date_from=date_from,
        date_to=date_to,
    )


def _make_query_plan(
    semantic_queries: tuple[str, ...] = ("boiler warranty letter", "heating guarantee"),
    keyword_terms: tuple[str, ...] = ("boiler", "warranty"),
    filter_candidates: FilterCandidates | None = None,
    sub_questions: tuple[str, ...] = ("When does the boiler warranty expire?",),
) -> QueryPlan:
    return QueryPlan(
        semantic_queries=semantic_queries,
        keyword_terms=keyword_terms,
        filter_candidates=filter_candidates or _make_filter_candidates(),
        sub_questions=sub_questions,
    )


# ---------------------------------------------------------------------------
# broaden_plan
# ---------------------------------------------------------------------------


class TestBroadenPlan:
    def test_returns_a_new_query_plan_instance(self) -> None:
        original = _make_query_plan()
        broadened = broaden_plan(original)
        assert broadened is not original

    def test_original_plan_is_unchanged(self) -> None:
        original = _make_query_plan()
        original_filters = original.filter_candidates
        broaden_plan(original)
        # frozen dataclass — mutation is structurally impossible, but confirm
        # the reference still points to the same object with same values.
        assert original.filter_candidates is original_filters
        assert original.filter_candidates.correspondent == "npower"

    def test_filter_candidates_are_cleared(self) -> None:
        original = _make_query_plan(
            filter_candidates=_make_filter_candidates(
                correspondent="npower",
                document_type="invoice",
                tags=("electricity",),
                date_from="2024-01-01",
                date_to="2024-12-31",
            )
        )
        broadened = broaden_plan(original)
        fc = broadened.filter_candidates
        assert fc.correspondent is None
        assert fc.document_type is None
        assert fc.tags == ()
        assert fc.date_from is None
        assert fc.date_to is None

    def test_semantic_queries_are_preserved(self) -> None:
        original = _make_query_plan(
            semantic_queries=("boiler warranty letter", "heating guarantee")
        )
        broadened = broaden_plan(original)
        assert broadened.semantic_queries == original.semantic_queries

    def test_keyword_terms_are_preserved(self) -> None:
        original = _make_query_plan(keyword_terms=("boiler", "warranty"))
        broadened = broaden_plan(original)
        assert broadened.keyword_terms == original.keyword_terms

    def test_sub_questions_are_preserved(self) -> None:
        original = _make_query_plan(
            sub_questions=("When does the boiler warranty expire?",)
        )
        broadened = broaden_plan(original)
        assert broadened.sub_questions == original.sub_questions

    def test_already_empty_filters_stay_empty(self) -> None:
        original = _make_query_plan(
            filter_candidates=FilterCandidates(
                correspondent=None,
                document_type=None,
                tags=(),
                date_from=None,
                date_to=None,
            )
        )
        broadened = broaden_plan(original)
        fc = broadened.filter_candidates
        assert fc.correspondent is None
        assert fc.document_type is None
        assert fc.tags == ()


# ---------------------------------------------------------------------------
# adjust_plan
# ---------------------------------------------------------------------------


class TestAdjustPlan:
    def test_returns_a_new_query_plan_instance(self) -> None:
        original = _make_query_plan()
        adjusted = adjust_plan(original, "include documents from 2018–2022")
        assert adjusted is not original

    def test_original_plan_is_unchanged(self) -> None:
        original = _make_query_plan(
            semantic_queries=("boiler warranty letter",),
            keyword_terms=("boiler",),
        )
        adjust_plan(original, "broaden to all heating documents")
        assert original.semantic_queries == ("boiler warranty letter",)
        assert original.keyword_terms == ("boiler",)

    def test_adjustment_text_appears_in_semantic_queries_or_keyword_terms(
        self,
    ) -> None:
        adjustment = "include documents from 2018 to 2022"
        original = _make_query_plan()
        adjusted = adjust_plan(original, adjustment)
        all_search_terms = " ".join(
            adjusted.semantic_queries + adjusted.keyword_terms
        )
        assert adjustment in all_search_terms

    def test_original_semantic_queries_are_preserved(self) -> None:
        original = _make_query_plan(
            semantic_queries=("boiler warranty letter", "heating guarantee")
        )
        adjusted = adjust_plan(original, "broaden to heating appliances generally")
        # Original queries must still be present.
        for query in original.semantic_queries:
            assert query in adjusted.semantic_queries

    def test_original_keyword_terms_are_preserved(self) -> None:
        original = _make_query_plan(keyword_terms=("boiler", "warranty"))
        adjusted = adjust_plan(original, "add gas safety certificate")
        for term in original.keyword_terms:
            assert term in adjusted.keyword_terms

    def test_original_sub_questions_are_preserved(self) -> None:
        original = _make_query_plan(
            sub_questions=("When does the boiler warranty expire?",)
        )
        adjusted = adjust_plan(original, "look at earlier documents")
        assert original.sub_questions == adjusted.sub_questions

    def test_original_filter_candidates_are_preserved(self) -> None:
        fc = _make_filter_candidates(correspondent="npower")
        original = _make_query_plan(filter_candidates=fc)
        adjusted = adjust_plan(original, "include more document types")
        assert adjusted.filter_candidates.correspondent == "npower"

    def test_adjusted_plan_has_more_queries_or_terms_than_original(self) -> None:
        original = _make_query_plan(
            semantic_queries=("boiler warranty",),
            keyword_terms=("boiler",),
        )
        adjusted = adjust_plan(original, "also check heating service records")
        total_original = len(original.semantic_queries) + len(original.keyword_terms)
        total_adjusted = len(adjusted.semantic_queries) + len(adjusted.keyword_terms)
        assert total_adjusted > total_original
