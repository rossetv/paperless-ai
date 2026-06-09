"""Tests for trace + cost mapping in ``search.wire.search`` (spec §Telemetry).

Verifies that :func:`~search.wire.search.to_search_response` maps the
:class:`~search.models.SearchTrace` and :class:`~search.models.CostSummary`
that now ride on every ``SearchResult.stats`` into the wire response — including
the ``None``-token / ``None``-cost passthrough for a non-LLM phase and the
``usd=None`` "unpriced" marker.
"""

from __future__ import annotations

from search.models import (
    Cost,
    CostSummary,
    PhaseRecord,
    SearchStats,
    SearchTrace,
    TokenUsage,
)
from search.wire.search import to_search_response
from tests.helpers.factories import make_search_result


def _result_with_trace() -> object:
    """A SearchResult whose stats carry a two-phase trace and a priced cost."""
    trace = SearchTrace(
        phases=(
            PhaseRecord(
                phase="plan",
                label="Planning the query",
                detail={"rewritten_query": "boiler warranty expiry"},
                tokens=TokenUsage(prompt=10, completion=4, reasoning=1, total=14),
                cost=Cost(usd=0.01, local=False),
                ms=42,
            ),
            PhaseRecord(
                phase="retrieve",
                label="Retrieving documents",
                detail={"chunk_count": 3, "doc_count": 2, "broadened": False},
                tokens=None,
                cost=None,
                ms=7,
            ),
        )
    )
    cost = CostSummary(
        tokens=TokenUsage(prompt=10, completion=4, reasoning=1, total=14),
        usd=0.01,
        local=False,
        llm_calls=1,
    )
    stats = SearchStats(
        llm_calls=1, latency_ms=49, refined=False, trace=trace, cost=cost
    )
    return make_search_result(stats=stats)


def test_to_search_response_includes_trace_and_cost() -> None:
    """The trace phases and the cost summary cross the wire boundary intact."""
    result = _result_with_trace()
    resp = to_search_response(result)  # type: ignore[arg-type]

    assert resp.cost.usd == 0.01
    assert resp.cost.tokens.total == 14
    assert resp.cost.llm_calls == 1
    assert resp.cost.local is False

    assert [p.phase for p in resp.trace.phases] == ["plan", "retrieve"]
    plan_phase = resp.trace.phases[0]
    assert plan_phase.detail["rewritten_query"] == "boiler warranty expiry"
    assert plan_phase.tokens is not None and plan_phase.tokens.completion == 4
    assert plan_phase.cost is not None and plan_phase.cost.usd == 0.01
    assert plan_phase.ms == 42


def test_non_llm_phase_maps_to_null_tokens_and_cost() -> None:
    """A retrieve phase (no LLM call) maps to null tokens and null cost."""
    resp = to_search_response(_result_with_trace())  # type: ignore[arg-type]
    retrieve_phase = resp.trace.phases[1]
    assert retrieve_phase.tokens is None
    assert retrieve_phase.cost is None
    assert retrieve_phase.detail["chunk_count"] == 3


def test_unpriced_cost_summary_maps_usd_none() -> None:
    """A cost summary with an unpriced call (usd=None) crosses as null usd."""
    stats = SearchStats(
        llm_calls=1,
        latency_ms=10,
        refined=False,
        trace=SearchTrace(phases=()),
        cost=CostSummary(
            tokens=TokenUsage(prompt=5, completion=2, reasoning=0, total=7),
            usd=None,
            local=False,
            llm_calls=1,
        ),
    )
    resp = to_search_response(make_search_result(stats=stats))
    assert resp.cost.usd is None
    assert resp.cost.tokens.total == 7


def test_default_result_carries_an_empty_trace_and_zero_cost() -> None:
    """A plain make_search_result (defaulted stats) still produces trace/cost.

    The new wire fields are required; the converter fills them from the
    defaulted ``SearchStats.trace``/``cost`` so existing callers do not break.
    """
    resp = to_search_response(make_search_result())
    assert resp.trace.phases == []
    assert resp.cost.tokens.total == 0
    assert resp.cost.llm_calls == 0
