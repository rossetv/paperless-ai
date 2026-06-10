"""Tests for ``outcome_kind`` serialisation in ``search.wire.search``.

Verifies that :func:`~search.wire.search.to_search_response` maps the
``outcome_kind`` field from :class:`~search.models.SearchResult` to the wire
model unchanged for all three discriminator values: ``"answered"``,
``"clarify"``, and ``"no_match"``.

The ``sources`` field is already empty for the retry kinds (tested by
``test_core_fail_fast``); here we confirm the discriminator travels to the
HTTP boundary correctly so the SPA can branch on it.
"""

from __future__ import annotations

from tests.helpers.factories import (
    make_retrieval_plan,
    make_search_result,
    make_search_stats,
)
from search.wire.search import to_search_response


def test_to_search_response_defaults_outcome_kind_to_answered() -> None:
    """A plain SearchResult with no explicit outcome_kind maps to 'answered'."""
    result = make_search_result()
    response = to_search_response(result)
    assert response.outcome_kind == "answered"


def test_to_search_response_maps_answered_outcome_kind() -> None:
    """outcome_kind='answered' round-trips through the wire mapper."""
    result = make_search_result(answer="The boiler was installed in 2021.")
    # outcome_kind defaults to "answered" — verify explicit construction too.
    from search.models import SearchResult

    answered_result = SearchResult(
        answer=result.answer,
        sources=result.sources,
        plan=result.plan,
        stats=result.stats,
        outcome_kind="answered",
    )
    response = to_search_response(answered_result)
    assert response.outcome_kind == "answered"


def test_to_search_response_maps_clarify_outcome_kind() -> None:
    """outcome_kind='clarify' travels through to_search_response unchanged."""
    from search.models import SearchResult

    plan = make_retrieval_plan()
    stats = make_search_stats()
    result = SearchResult(
        answer="Could you be more specific? Try including a document type or date range.",
        sources=(),
        plan=plan,
        stats=stats,
        outcome_kind="clarify",
    )
    response = to_search_response(result)
    assert response.outcome_kind == "clarify"
    # The nudge message is in the answer field.
    assert "more specific" in response.answer
    # Sources are empty for clarify results.
    assert response.sources == []


def test_to_search_response_maps_no_match_outcome_kind() -> None:
    """outcome_kind='no_match' travels through to_search_response unchanged."""
    from search.models import SearchResult

    plan = make_retrieval_plan()
    stats = make_search_stats()
    result = SearchResult(
        answer="No relevant documents were found. Try rephrasing your question.",
        sources=(),
        plan=plan,
        stats=stats,
        outcome_kind="no_match",
    )
    response = to_search_response(result)
    assert response.outcome_kind == "no_match"
    assert "No relevant documents" in response.answer
    assert response.sources == []
