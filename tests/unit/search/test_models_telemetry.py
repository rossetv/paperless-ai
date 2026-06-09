"""Tests for the telemetry value types added to search.models (Phase 1, Task 1)."""

from search.models import TokenUsage, Cost, PhaseRecord, SearchTrace, CostSummary


def test_token_usage_holds_the_four_counts():
    u = TokenUsage(prompt=10, completion=20, reasoning=5, total=30)
    assert (u.prompt, u.completion, u.reasoning, u.total) == (10, 20, 5, 30)


def test_cost_carries_optional_usd_and_local_flag():
    assert Cost(usd=None, local=False).usd is None
    assert Cost(usd=0.0, local=True).local is True


def test_phase_record_allows_none_tokens_for_non_llm_phase():
    pr = PhaseRecord(
        phase="retrieve",
        label="Retrieving",
        detail={"chunk_count": 3},
        tokens=None,
        cost=None,
        ms=12,
    )
    assert pr.tokens is None and pr.detail["chunk_count"] == 3


def test_search_trace_and_cost_summary_compose():
    pr = PhaseRecord(
        phase="judge", label="Judging", detail={}, tokens=None, cost=None, ms=1
    )
    trace = SearchTrace(phases=(pr,))
    cs = CostSummary(tokens=TokenUsage(1, 2, 0, 3), usd=0.001, local=False, llm_calls=2)
    assert trace.phases[0].phase == "judge" and cs.llm_calls == 2


def test_search_stats_carries_trace_and_cost():
    from search.models import CostSummary, SearchStats, SearchTrace, TokenUsage

    stats = SearchStats(
        llm_calls=2,
        latency_ms=10,
        refined=False,
        trace=SearchTrace(()),
        cost=CostSummary(TokenUsage(0, 0, 0, 0), None, False, 0),
    )
    assert stats.trace.phases == () and stats.cost.llm_calls == 0


def test_search_stats_trace_and_cost_default_to_empty():
    from search.models import SearchStats

    stats = SearchStats(llm_calls=0, latency_ms=0, refined=False)
    assert stats.trace.phases == ()
    assert stats.cost.llm_calls == 0
    assert stats.cost.tokens == TokenUsage(0, 0, 0, 0)
    assert stats.cost.usd is None and stats.cost.local is False
