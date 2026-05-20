"""Tests for src/search/models.py.

Verifies:
- Every dataclass is frozen (mutation raises FrozenInstanceError).
- Every dataclass can be constructed with the documented fields.
- AnswerOutcome discriminated union narrows correctly with isinstance checks.
"""

from __future__ import annotations

import pytest

from search.models import (
    AnswerOutcome,
    Answered,
    FilterCandidates,
    NeedsMore,
    QueryPlan,
    RetrievedChunk,
    SearchResult,
    SearchStats,
    SourceDocument,
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
# QueryPlan
# ---------------------------------------------------------------------------


class TestQueryPlan:
    def test_construction_with_all_fields(self) -> None:
        fc = FilterCandidates(
            correspondent=None,
            document_type=None,
            tags=(),
            date_from=None,
            date_to=None,
        )
        plan = QueryPlan(
            semantic_queries=("boiler warranty", "heating system guarantee"),
            keyword_terms=("boiler", "warranty"),
            filter_candidates=fc,
            sub_questions=("When was the boiler installed?",),
        )
        assert plan.semantic_queries == ("boiler warranty", "heating system guarantee")
        assert plan.keyword_terms == ("boiler", "warranty")
        assert plan.filter_candidates is fc
        assert plan.sub_questions == ("When was the boiler installed?",)

    def test_is_frozen(self) -> None:
        fc = FilterCandidates(
            correspondent=None,
            document_type=None,
            tags=(),
            date_from=None,
            date_to=None,
        )
        plan = QueryPlan(
            semantic_queries=(),
            keyword_terms=(),
            filter_candidates=fc,
            sub_questions=(),
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            plan.semantic_queries = ("changed",)  # type: ignore[misc]


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
    def _make_source_document(self, document_id: int = 1) -> SourceDocument:
        return SourceDocument(
            document_id=document_id,
            title=None,
            correspondent=None,
            document_type=None,
            created=None,
            snippet="snippet",
            paperless_url=f"https://paperless.local/documents/{document_id}/",
            score=0.5,
        )

    def _make_query_plan(self) -> QueryPlan:
        return QueryPlan(
            semantic_queries=(),
            keyword_terms=(),
            filter_candidates=FilterCandidates(
                correspondent=None,
                document_type=None,
                tags=(),
                date_from=None,
                date_to=None,
            ),
            sub_questions=(),
        )

    def test_construction(self) -> None:
        doc = self._make_source_document()
        plan = self._make_query_plan()
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
        doc = self._make_source_document()
        plan = self._make_query_plan()
        stats = SearchStats(llm_calls=1, latency_ms=200, refined=False)
        search_result = SearchResult(
            answer="answer",
            sources=(doc,),
            plan=plan,
            stats=stats,
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
