"""Tests for src/search/refinement.py.

Verifies the contract of the three pure helpers:
- broaden_plan: drops filter candidates, preserves the rest.
- adjust_plan: incorporates an adjustment hint, preserves the original content.
- merge_chunks: unions two retrieved-chunk rounds, de-duplicating by chunk id.
All return new objects without mutating their inputs.
"""

from __future__ import annotations

from typing import Any

from search.models import FilterCandidates, QueryPlan
from search.refinement import adjust_plan, broaden_plan, merge_chunks
from tests.helpers.factories import (
    make_filter_candidates,
    make_query_plan,
    make_retrieved_chunk,
)


def _populated_filter_candidates() -> FilterCandidates:
    """A FilterCandidates with every field set — the broaden_plan input."""
    return make_filter_candidates(
        correspondent="npower",
        document_type="invoice",
        tags=("electricity",),
        date_from="2024-01-01",
        date_to="2024-12-31",
    )


def _populated_plan(**overrides: Any) -> QueryPlan:
    """A QueryPlan with populated queries, keywords, filters, and sub-questions."""
    fields: dict[str, Any] = {
        "semantic_queries": ("boiler warranty letter", "heating guarantee"),
        "keyword_terms": ("boiler", "warranty"),
        "filter_candidates": _populated_filter_candidates(),
        "sub_questions": ("When does the boiler warranty expire?",),
    }
    fields.update(overrides)
    return make_query_plan(**fields)


# ---------------------------------------------------------------------------
# broaden_plan
# ---------------------------------------------------------------------------


class TestBroadenPlan:
    def test_returns_a_new_query_plan_instance(self) -> None:
        original = _populated_plan()
        broadened = broaden_plan(original)
        assert broadened is not original

    def test_original_plan_is_unchanged(self) -> None:
        original = _populated_plan()
        original_filters = original.filter_candidates
        broaden_plan(original)
        # frozen dataclass — mutation is structurally impossible, but confirm
        # the reference still points to the same object with same values.
        assert original.filter_candidates is original_filters
        assert original.filter_candidates.correspondent == "npower"

    def test_filter_candidates_are_cleared(self) -> None:
        broadened = broaden_plan(_populated_plan())
        fc = broadened.filter_candidates
        assert fc.correspondent is None
        assert fc.document_type is None
        assert fc.tags == ()
        assert fc.date_from is None
        assert fc.date_to is None

    def test_semantic_queries_are_preserved(self) -> None:
        original = _populated_plan()
        broadened = broaden_plan(original)
        assert broadened.semantic_queries == original.semantic_queries

    def test_keyword_terms_are_preserved(self) -> None:
        original = _populated_plan()
        broadened = broaden_plan(original)
        assert broadened.keyword_terms == original.keyword_terms

    def test_sub_questions_are_preserved(self) -> None:
        original = _populated_plan()
        broadened = broaden_plan(original)
        assert broadened.sub_questions == original.sub_questions

    def test_already_empty_filters_stay_empty(self) -> None:
        original = _populated_plan(filter_candidates=make_filter_candidates())
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
        original = _populated_plan()
        adjusted = adjust_plan(original, "include documents from 2018–2022")
        assert adjusted is not original

    def test_original_plan_is_unchanged(self) -> None:
        original = _populated_plan(
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
        adjusted = adjust_plan(_populated_plan(), adjustment)
        all_search_terms = " ".join(
            adjusted.semantic_queries + adjusted.keyword_terms
        )
        assert adjustment in all_search_terms

    def test_original_semantic_queries_are_preserved(self) -> None:
        original = _populated_plan(
            semantic_queries=("boiler warranty letter", "heating guarantee")
        )
        adjusted = adjust_plan(original, "broaden to heating appliances generally")
        for query in original.semantic_queries:
            assert query in adjusted.semantic_queries

    def test_original_keyword_terms_are_preserved(self) -> None:
        original = _populated_plan(keyword_terms=("boiler", "warranty"))
        adjusted = adjust_plan(original, "add gas safety certificate")
        for term in original.keyword_terms:
            assert term in adjusted.keyword_terms

    def test_original_sub_questions_are_preserved(self) -> None:
        original = _populated_plan(
            sub_questions=("When does the boiler warranty expire?",)
        )
        adjusted = adjust_plan(original, "look at earlier documents")
        assert original.sub_questions == adjusted.sub_questions

    def test_original_filter_candidates_are_preserved(self) -> None:
        original = _populated_plan()
        adjusted = adjust_plan(original, "include more document types")
        assert adjusted.filter_candidates.correspondent == "npower"

    def test_adjusted_plan_has_more_queries_or_terms_than_original(self) -> None:
        original = _populated_plan(
            semantic_queries=("boiler warranty",), keyword_terms=("boiler",)
        )
        adjusted = adjust_plan(original, "also check heating service records")
        total_original = len(original.semantic_queries) + len(
            original.keyword_terms
        )
        total_adjusted = len(adjusted.semantic_queries) + len(
            adjusted.keyword_terms
        )
        assert total_adjusted > total_original


# ---------------------------------------------------------------------------
# merge_chunks
# ---------------------------------------------------------------------------


class TestMergeChunks:
    """merge_chunks unions two retrieval rounds, de-duplicating by chunk id."""

    def test_disjoint_rounds_are_concatenated(self) -> None:
        previous = [make_retrieved_chunk(chunk_id=1, document_id=1, rrf_score=0.9)]
        new = [make_retrieved_chunk(chunk_id=2, document_id=2, rrf_score=0.5)]
        merged = merge_chunks(previous, new)
        assert {chunk.chunk_id for chunk in merged} == {1, 2}

    def test_chunk_in_both_rounds_is_kept_once(self) -> None:
        shared = make_retrieved_chunk(chunk_id=1, document_id=1, rrf_score=0.9)
        previous = [shared]
        new = [
            make_retrieved_chunk(chunk_id=1, document_id=1, rrf_score=0.4),
            make_retrieved_chunk(chunk_id=2, document_id=2, rrf_score=0.3),
        ]
        merged = merge_chunks(previous, new)
        chunk_ids = [chunk.chunk_id for chunk in merged]
        assert chunk_ids.count(1) == 1
        assert set(chunk_ids) == {1, 2}

    def test_merged_list_is_ordered_by_rrf_score_descending(self) -> None:
        previous = [make_retrieved_chunk(chunk_id=1, document_id=1, rrf_score=0.2)]
        new = [make_retrieved_chunk(chunk_id=2, document_id=2, rrf_score=0.8)]
        merged = merge_chunks(previous, new)
        scores = [chunk.rrf_score for chunk in merged]
        assert scores == sorted(scores, reverse=True)
