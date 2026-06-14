"""Tests for src/search/refinement.py.

Verifies the contract of the pure helpers:
- broaden_plan: clears every spec's filter guess, preserves the rest.
- merge_chunks: unions two retrieved-chunk rounds, de-duplicating by chunk id.
- trivial_plan: builds the planner-fallback-shaped plan (RAG-08).
- raw_rag_plan: builds the deterministic two-spec hybrid (vector + FTS) plan.
All return new objects without mutating their inputs.
"""

from __future__ import annotations

from search.models import (
    EMPTY_FILTER_CANDIDATES,
    PlannedSpec,
    RetrievalPlan,
)
from search.refinement import (
    broaden_plan,
    merge_chunks,
    raw_rag_plan,
    trivial_plan,
)
from tests.helpers.factories import (
    make_filter_candidates,
    make_retrieved_chunk,
)


def _populated_spec(*, semantic: str = "boiler warranty letter") -> PlannedSpec:
    """A PlannedSpec with a populated filter guess — the broaden_plan input."""
    return PlannedSpec(
        mode="semantic",
        semantic=semantic,
        keywords=("boiler", "warranty"),
        filter_guess=make_filter_candidates(
            correspondent="npower",
            document_type="invoice",
            tags=("electricity",),
            date_from="2024-01-01",
            date_to="2024-12-31",
        ),
        rationale="semantic pass for boiler warranty",
    )


def _populated_plan() -> RetrievalPlan:
    """A RetrievalPlan with two populated specs and no clarify."""
    return RetrievalPlan(
        specs=(
            _populated_spec(semantic="boiler warranty letter"),
            _populated_spec(semantic="heating guarantee"),
        ),
        clarify=None,
    )


# ---------------------------------------------------------------------------
# broaden_plan
# ---------------------------------------------------------------------------


class TestBroadenPlan:
    def test_returns_a_new_retrieval_plan_instance(self) -> None:
        original = _populated_plan()
        broadened = broaden_plan(original)
        assert broadened is not original
        assert isinstance(broadened, RetrievalPlan)

    def test_original_plan_is_unchanged(self) -> None:
        original = _populated_plan()
        broaden_plan(original)
        # frozen dataclass — mutation is structurally impossible, but confirm
        # the original spec still carries its filter guess.
        assert original.specs[0].filter_guess.correspondent == "npower"

    def test_every_spec_filter_guess_is_cleared(self) -> None:
        broadened = broaden_plan(_populated_plan())
        for spec in broadened.specs:
            assert spec.filter_guess is EMPTY_FILTER_CANDIDATES
            assert spec.filter_guess.correspondent is None
            assert spec.filter_guess.document_type is None
            assert spec.filter_guess.tags == ()
            assert spec.filter_guess.date_from is None
            assert spec.filter_guess.date_to is None

    def test_spec_count_and_order_are_preserved(self) -> None:
        original = _populated_plan()
        broadened = broaden_plan(original)
        assert len(broadened.specs) == len(original.specs)

    def test_mode_semantic_keywords_rationale_are_preserved(self) -> None:
        original = _populated_plan()
        broadened = broaden_plan(original)
        for original_spec, broadened_spec in zip(original.specs, broadened.specs):
            assert broadened_spec.mode == original_spec.mode
            assert broadened_spec.semantic == original_spec.semantic
            assert broadened_spec.keywords == original_spec.keywords
            assert broadened_spec.rationale == original_spec.rationale

    def test_clarify_is_preserved(self) -> None:
        original = RetrievalPlan(specs=(_populated_spec(),), clarify=None)
        broadened = broaden_plan(original)
        assert broadened.clarify is None

    def test_already_empty_filters_stay_empty(self) -> None:
        original = RetrievalPlan(
            specs=(
                PlannedSpec(
                    mode="semantic",
                    semantic="q",
                    keywords=(),
                    filter_guess=EMPTY_FILTER_CANDIDATES,
                    rationale="r",
                ),
            ),
            clarify=None,
        )
        broadened = broaden_plan(original)
        assert broadened.specs[0].filter_guess is EMPTY_FILTER_CANDIDATES

    def test_empty_plan_yields_empty_plan(self) -> None:
        broadened = broaden_plan(RetrievalPlan(specs=(), clarify=None))
        assert broadened.specs == ()


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


class TestTrivialPlan:
    """trivial_plan returns one broad semantic spec on the raw query (RAG-08)."""

    def test_sole_spec_is_a_semantic_search_on_the_raw_query(self) -> None:
        plan = trivial_plan("council tax")
        assert len(plan.specs) == 1
        spec = plan.specs[0]
        assert spec.mode == "semantic"
        assert spec.semantic == "council tax"

    def test_spec_has_empty_keywords_and_filters(self) -> None:
        spec = trivial_plan("council tax").specs[0]
        assert spec.keywords == ()
        assert spec.filter_guess == EMPTY_FILTER_CANDIDATES

    def test_returns_a_retrieval_plan_with_no_clarify(self) -> None:
        plan = trivial_plan("x")
        assert isinstance(plan, RetrievalPlan)
        assert plan.clarify is None


class TestRawRagPlan:
    """raw_rag_plan returns a deterministic hybrid vector+FTS plan, no LLM."""

    def test_emits_a_semantic_and_a_keyword_spec(self) -> None:
        plan = raw_rag_plan("boiler warranty 2024")
        assert [spec.mode for spec in plan.specs] == ["semantic", "keyword"]
        assert plan.clarify is None

    def test_semantic_spec_carries_the_raw_query(self) -> None:
        semantic = next(
            s for s in raw_rag_plan("boiler warranty").specs if s.mode == "semantic"
        )
        assert semantic.semantic == "boiler warranty"
        assert semantic.keywords == ()
        assert semantic.filter_guess == EMPTY_FILTER_CANDIDATES

    def test_keyword_spec_tokenises_the_query(self) -> None:
        keyword = next(
            s for s in raw_rag_plan("boiler warranty").specs if s.mode == "keyword"
        )
        assert keyword.keywords == ("boiler", "warranty")
        assert keyword.semantic is None
        assert keyword.filter_guess == EMPTY_FILTER_CANDIDATES

    def test_returns_a_retrieval_plan(self) -> None:
        assert isinstance(raw_rag_plan("x").specs, tuple)
        assert isinstance(raw_rag_plan("x"), RetrievalPlan)
