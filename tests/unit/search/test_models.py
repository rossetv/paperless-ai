"""Tests for src/search/models.py.

Verifies:
- Every dataclass is frozen (mutation raises FrozenInstanceError).
- Every dataclass can be constructed with the documented fields.
- AnswerOutcome discriminated union narrows correctly with isinstance checks.
- ClarifyNeeded, RetrievalSignal, and PlanOutcome (Task 2 additions) behave
  correctly.
- SearchResult.outcome_kind defaults to "answered" and accepts explicit values.
- PlannedSpec, RetrievalSpec, and RetrievalPlan (multi-spec plan dataclasses).
"""

from __future__ import annotations

import dataclasses

import pytest

from search.models import (
    AnswerOutcome,
    Answered,
    ClarifyNeeded,
    FilterCandidates,
    NeedsMore,
    PlanOutcome,
    PlannedSpec,
    RetrievalPlan,
    RetrievalSignal,
    RetrievalSpec,
    RetrievedChunk,
    SearchResult,
    SearchStats,
    SourceDocument,
)
from store.models import SearchFilters
from tests.helpers.factories import (
    make_retrieval_plan,
    make_search_stats,
    make_source_document,
)


# ---------------------------------------------------------------------------
# FilterCandidates
# ---------------------------------------------------------------------------


class TestFilterCandidates:
    def test_construction_with_all_fields(self) -> None:
        fc = FilterCandidates(
            correspondent="npower",
            document_type="invoice",
            tags=("electricity", "utility"),
            date_from="2024-01-01",
            date_to="2024-12-31",
        )
        assert fc.correspondent == "npower"
        assert fc.document_type == "invoice"
        assert fc.tags == ("electricity", "utility")
        assert fc.date_from == "2024-01-01"
        assert fc.date_to == "2024-12-31"

    def test_construction_with_optional_fields_as_none(self) -> None:
        fc = FilterCandidates(
            correspondent=None,
            document_type=None,
            tags=(),
            date_from=None,
            date_to=None,
        )
        assert fc.correspondent is None
        assert fc.document_type is None
        assert fc.tags == ()
        assert fc.date_from is None
        assert fc.date_to is None

    def test_is_frozen(self) -> None:
        fc = FilterCandidates(
            correspondent="npower",
            document_type=None,
            tags=(),
            date_from=None,
            date_to=None,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            fc.correspondent = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RetrievedChunk
# ---------------------------------------------------------------------------


class TestRetrievedChunk:
    def test_construction_with_all_fields(self) -> None:
        chunk = RetrievedChunk(
            chunk_id=42,
            document_id=7,
            text="The boiler warranty expires in 2030.",
            page_hint=3,
            rrf_score=0.0167,
        )
        assert chunk.chunk_id == 42
        assert chunk.document_id == 7
        assert chunk.text == "The boiler warranty expires in 2030."
        assert chunk.page_hint == 3
        assert chunk.rrf_score == pytest.approx(0.0167)

    def test_page_hint_can_be_none(self) -> None:
        chunk = RetrievedChunk(
            chunk_id=1,
            document_id=1,
            text="some text",
            page_hint=None,
            rrf_score=0.01,
        )
        assert chunk.page_hint is None

    def test_is_frozen(self) -> None:
        chunk = RetrievedChunk(
            chunk_id=1,
            document_id=1,
            text="text",
            page_hint=None,
            rrf_score=0.01,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            chunk.text = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SourceDocument
# ---------------------------------------------------------------------------


class TestSourceDocument:
    def test_construction_with_all_fields(self) -> None:
        doc = SourceDocument(
            document_id=7,
            title="Boiler Warranty Certificate",
            correspondent="Worcester Bosch",
            document_type="Warranty",
            created="2020-03-15",
            snippet="The boiler warranty expires in 2030.",
            paperless_url="https://paperless.local/documents/7/",
            score=0.85,
        )
        assert doc.document_id == 7
        assert doc.title == "Boiler Warranty Certificate"
        assert doc.correspondent == "Worcester Bosch"
        assert doc.document_type == "Warranty"
        assert doc.created == "2020-03-15"
        assert doc.snippet == "The boiler warranty expires in 2030."
        assert doc.paperless_url == "https://paperless.local/documents/7/"
        assert doc.score == pytest.approx(0.85)

    def test_optional_fields_can_be_none(self) -> None:
        doc = SourceDocument(
            document_id=1,
            title=None,
            correspondent=None,
            document_type=None,
            created=None,
            snippet="",
            paperless_url="https://paperless.local/documents/1/",
            score=0.0,
        )
        assert doc.title is None
        assert doc.correspondent is None
        assert doc.document_type is None
        assert doc.created is None

    def test_is_frozen(self) -> None:
        doc = SourceDocument(
            document_id=1,
            title=None,
            correspondent=None,
            document_type=None,
            created=None,
            snippet="snippet",
            paperless_url="https://paperless.local/documents/1/",
            score=0.5,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            doc.score = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SearchStats
# ---------------------------------------------------------------------------


class TestSearchStats:
    def test_construction(self) -> None:
        stats = SearchStats(llm_calls=2, latency_ms=450, refined=True)
        assert stats.llm_calls == 2
        assert stats.latency_ms == 450
        assert stats.refined is True

    def test_is_frozen(self) -> None:
        stats = SearchStats(llm_calls=1, latency_ms=100, refined=False)
        with pytest.raises(Exception):  # FrozenInstanceError
            stats.llm_calls = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------


class TestSearchResult:
    """SearchResult composes a SourceDocument, a RetrievalPlan, and SearchStats.

    The composed parts are built via the shared factories (CODE_GUIDELINES
    §11.5) — only SearchResult itself is the shape under test here.
    """

    def test_construction(self) -> None:
        doc = make_source_document()
        plan = make_retrieval_plan()
        stats = SearchStats(llm_calls=1, latency_ms=200, refined=False)
        search_result = SearchResult(
            answer="The boiler warranty expires in 2030.",
            sources=(doc,),
            plan=plan,
            stats=stats,
        )
        assert search_result.answer == "The boiler warranty expires in 2030."
        assert search_result.sources == (doc,)
        assert search_result.plan is plan
        assert search_result.stats is stats

    def test_is_frozen(self) -> None:
        search_result = SearchResult(
            answer="answer",
            sources=(make_source_document(),),
            plan=make_retrieval_plan(),
            stats=SearchStats(llm_calls=1, latency_ms=200, refined=False),
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            search_result.answer = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Answered
# ---------------------------------------------------------------------------


class TestAnswered:
    def test_construction(self) -> None:
        answered = Answered(
            answer="The warranty expires in 2030.",
            citations=(7, 12),
        )
        assert answered.answer == "The warranty expires in 2030."
        assert answered.citations == (7, 12)

    def test_is_frozen(self) -> None:
        answered = Answered(answer="answer", citations=(1,))
        with pytest.raises(Exception):  # FrozenInstanceError
            answered.answer = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# NeedsMore
# ---------------------------------------------------------------------------


class TestNeedsMore:
    def test_construction(self) -> None:
        needs_more = NeedsMore(adjustment="broaden date range to 2018–2025")
        assert needs_more.adjustment == "broaden date range to 2018–2025"

    def test_is_frozen(self) -> None:
        needs_more = NeedsMore(adjustment="original")
        with pytest.raises(Exception):  # FrozenInstanceError
            needs_more.adjustment = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AnswerOutcome discriminated union narrowing
# ---------------------------------------------------------------------------


class TestAnswerOutcome:
    def test_answered_isinstance_narrowing(self) -> None:
        outcome: AnswerOutcome = Answered(answer="yes", citations=(3,))
        assert isinstance(outcome, Answered)
        assert not isinstance(outcome, NeedsMore)

    def test_needs_more_isinstance_narrowing(self) -> None:
        outcome: AnswerOutcome = NeedsMore(adjustment="try broader terms")
        assert isinstance(outcome, NeedsMore)
        assert not isinstance(outcome, Answered)

    def test_answered_carries_correct_payload(self) -> None:
        outcome: AnswerOutcome = Answered(answer="42", citations=(1, 2, 3))
        assert isinstance(outcome, Answered)
        assert outcome.answer == "42"
        assert outcome.citations == (1, 2, 3)

    def test_needs_more_carries_correct_payload(self) -> None:
        outcome: AnswerOutcome = NeedsMore(adjustment="include earlier documents")
        assert isinstance(outcome, NeedsMore)
        assert outcome.adjustment == "include earlier documents"


# ---------------------------------------------------------------------------
# ClarifyNeeded (Layer 1 fail-fast signal)
# ---------------------------------------------------------------------------


class TestClarifyNeeded:
    def test_construction(self) -> None:
        cn = ClarifyNeeded(reason="Query is too vague to produce a useful search plan.")
        assert cn.reason == "Query is too vague to produce a useful search plan."

    def test_is_frozen(self) -> None:
        cn = ClarifyNeeded(reason="original reason")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cn.reason = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RetrievalSignal (Layer 2 fail-fast signal)
# ---------------------------------------------------------------------------


class TestRetrievalSignal:
    def test_construction_with_vector_similarity(self) -> None:
        sig = RetrievalSignal(best_vector_similarity=0.42, has_keyword_hit=True)
        assert sig.best_vector_similarity == pytest.approx(0.42)
        assert sig.has_keyword_hit is True

    def test_construction_without_vector_search(self) -> None:
        sig = RetrievalSignal(best_vector_similarity=None, has_keyword_hit=False)
        assert sig.best_vector_similarity is None
        assert sig.has_keyword_hit is False

    def test_is_frozen(self) -> None:
        sig = RetrievalSignal(best_vector_similarity=0.5, has_keyword_hit=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            sig.has_keyword_hit = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PlanOutcome discriminated union narrowing
# ---------------------------------------------------------------------------


class TestPlanOutcome:
    def test_retrieval_plan_is_a_valid_plan_outcome(self) -> None:
        outcome: PlanOutcome = make_retrieval_plan()
        assert isinstance(outcome, RetrievalPlan)
        assert not isinstance(outcome, ClarifyNeeded)

    def test_clarify_needed_is_a_valid_plan_outcome(self) -> None:
        outcome: PlanOutcome = ClarifyNeeded(reason="too vague")
        assert isinstance(outcome, ClarifyNeeded)
        assert not isinstance(outcome, RetrievalPlan)


# ---------------------------------------------------------------------------
# SearchResult.outcome_kind discriminator field
# ---------------------------------------------------------------------------


class TestSearchResultOutcomeKind:
    def test_defaults_to_answered(self) -> None:
        result = SearchResult(
            answer="The answer.",
            sources=(make_source_document(),),
            plan=make_retrieval_plan(),
            stats=make_search_stats(),
        )
        assert result.outcome_kind == "answered"

    def test_explicit_clarify_round_trips(self) -> None:
        result = SearchResult(
            answer="Please clarify your query.",
            sources=(),
            plan=make_retrieval_plan(),
            stats=make_search_stats(),
            outcome_kind="clarify",
        )
        assert result.outcome_kind == "clarify"

    def test_explicit_no_match_round_trips(self) -> None:
        result = SearchResult(
            answer="No documents matched your query.",
            sources=(),
            plan=make_retrieval_plan(),
            stats=make_search_stats(),
            outcome_kind="no_match",
        )
        assert result.outcome_kind == "no_match"

    def test_outcome_kind_field_is_frozen(self) -> None:
        result = SearchResult(
            answer="answer",
            sources=(),
            plan=make_retrieval_plan(),
            stats=make_search_stats(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.outcome_kind = "clarify"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PlannedSpec (multi-spec plan dataclass — Phase 1)
# ---------------------------------------------------------------------------


def _make_filter_candidates(
    *,
    correspondent: str | None = None,
    document_type: str | None = None,
    tags: tuple[str, ...] = (),
    date_from: str | None = None,
    date_to: str | None = None,
) -> FilterCandidates:
    return FilterCandidates(
        correspondent=correspondent,
        document_type=document_type,
        tags=tags,
        date_from=date_from,
        date_to=date_to,
    )


def _make_search_filters(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    correspondent_id: int | None = None,
    document_type_id: int | None = None,
    tag_ids: tuple[int, ...] = (),
) -> SearchFilters:
    return SearchFilters(
        date_from=date_from,
        date_to=date_to,
        correspondent_id=correspondent_id,
        document_type_id=document_type_id,
        tag_ids=tag_ids,
    )


class TestPlannedSpec:
    def test_construction_semantic_mode(self) -> None:
        fc = _make_filter_candidates(correspondent="npower")
        spec = PlannedSpec(
            mode="semantic",
            semantic="electricity bill npower 2024",
            keywords=(),
            filter_guess=fc,
            rationale="User asked about energy bills.",
        )
        assert spec.mode == "semantic"
        assert spec.semantic == "electricity bill npower 2024"
        assert spec.keywords == ()
        assert spec.filter_guess is fc
        assert spec.rationale == "User asked about energy bills."

    def test_construction_keyword_mode(self) -> None:
        fc = _make_filter_candidates()
        spec = PlannedSpec(
            mode="keyword",
            semantic=None,
            keywords=("invoice", "2024"),
            filter_guess=fc,
            rationale="Exact reference lookup.",
        )
        assert spec.mode == "keyword"
        assert spec.semantic is None
        assert spec.keywords == ("invoice", "2024")

    def test_is_frozen(self) -> None:
        spec = PlannedSpec(
            mode="semantic",
            semantic="query",
            keywords=(),
            filter_guess=_make_filter_candidates(),
            rationale="r",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.semantic = "changed"  # type: ignore[misc]

    def test_field_values_round_trip(self) -> None:
        fc = _make_filter_candidates(tags=("utility", "electricity"))
        spec = PlannedSpec(
            mode="keyword",
            semantic=None,
            keywords=("npower", "direct debit"),
            filter_guess=fc,
            rationale="Keyword pass for exact account reference.",
        )
        assert spec.filter_guess.tags == ("utility", "electricity")
        assert spec.keywords == ("npower", "direct debit")
        assert spec.rationale == "Keyword pass for exact account reference."


# ---------------------------------------------------------------------------
# RetrievalSpec (resolved, ready-for-store search)
# ---------------------------------------------------------------------------


class TestRetrievalSpec:
    def test_construction(self) -> None:
        sf = _make_search_filters(correspondent_id=7, tag_ids=(3, 9))
        spec = RetrievalSpec(
            mode="semantic",
            semantic="boiler warranty certificate",
            keywords=(),
            filters=sf,
            rationale="Semantic pass on boiler warranty.",
        )
        assert spec.mode == "semantic"
        assert spec.semantic == "boiler warranty certificate"
        assert spec.keywords == ()
        assert spec.filters is sf
        assert spec.rationale == "Semantic pass on boiler warranty."

    def test_construction_keyword_mode(self) -> None:
        sf = _make_search_filters()
        spec = RetrievalSpec(
            mode="keyword",
            semantic=None,
            keywords=("boiler", "warranty"),
            filters=sf,
            rationale="FTS pass for boiler + warranty.",
        )
        assert spec.mode == "keyword"
        assert spec.semantic is None
        assert spec.keywords == ("boiler", "warranty")

    def test_is_frozen(self) -> None:
        sf = _make_search_filters()
        spec = RetrievalSpec(
            mode="semantic",
            semantic="q",
            keywords=(),
            filters=sf,
            rationale="r",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.mode = "keyword"  # type: ignore[misc]

    def test_field_values_round_trip(self) -> None:
        sf = _make_search_filters(
            date_from="2023-01-01",
            date_to="2023-12-31",
            document_type_id=2,
        )
        spec = RetrievalSpec(
            mode="semantic",
            semantic="insurance renewal",
            keywords=("renewal",),
            filters=sf,
            rationale="Annual insurance renewal lookup.",
        )
        assert spec.filters.date_from == "2023-01-01"
        assert spec.filters.date_to == "2023-12-31"
        assert spec.filters.document_type_id == 2


# ---------------------------------------------------------------------------
# RetrievalPlan (the planner's structured output)
# ---------------------------------------------------------------------------


class TestRetrievalPlan:
    def test_construction_with_two_specs_and_no_clarify(self) -> None:
        spec_a = PlannedSpec(
            mode="semantic",
            semantic="energy bill npower",
            keywords=(),
            filter_guess=_make_filter_candidates(correspondent="npower"),
            rationale="Semantic pass for energy bills.",
        )
        spec_b = PlannedSpec(
            mode="keyword",
            semantic=None,
            keywords=("npower", "direct debit"),
            filter_guess=_make_filter_candidates(),
            rationale="Keyword pass for exact reference.",
        )
        plan = RetrievalPlan(specs=(spec_a, spec_b), clarify=None)
        assert len(plan.specs) == 2
        assert plan.specs[0] is spec_a
        assert plan.specs[1] is spec_b
        assert plan.clarify is None

    def test_clarify_defaults_to_none(self) -> None:
        plan = RetrievalPlan(specs=())
        assert plan.clarify is None

    def test_construction_with_clarify_signal(self) -> None:
        cn = ClarifyNeeded(reason="Query is too vague.")
        plan = RetrievalPlan(specs=(), clarify=cn)
        assert plan.clarify is cn
        assert plan.specs == ()

    def test_is_frozen(self) -> None:
        plan = RetrievalPlan(specs=())
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.clarify = ClarifyNeeded(reason="late")  # type: ignore[misc]

    def test_specs_field_round_trips(self) -> None:
        spec = PlannedSpec(
            mode="semantic",
            semantic="passport expiry",
            keywords=(),
            filter_guess=_make_filter_candidates(),
            rationale="Single-spec plan.",
        )
        plan = RetrievalPlan(specs=(spec,))
        assert plan.specs[0].semantic == "passport expiry"
