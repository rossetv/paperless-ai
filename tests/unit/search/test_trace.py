"""Tests for the _Telemetry accumulator and phase events in search.trace (Task 4)."""

from search.models import LlmCallUsage, PhaseRecord, TokenUsage
from search.trace import PhaseStart, _Telemetry


def test_done_summarises_sink_prices_and_emits():
    events = []
    tele = _Telemetry(on_event=events.append, provider="openai")
    tele.start("judge", "Judging relevance")
    sink = [
        LlmCallUsage(
            model="gpt-5.4-mini",
            prompt=1_000_000,
            completion=0,
            reasoning=0,
            total=1_000_000,
        )
    ]
    tele.done(
        "judge",
        "Judging relevance",
        {"kept": 2},
        usage_sink=sink,
        started=0.0,
        now=lambda: 0.05,
    )
    assert isinstance(events[0], PhaseStart) and events[0].phase == "judge"
    rec = events[1]
    assert isinstance(rec, PhaseRecord)
    assert rec.detail == {"kept": 2}
    assert rec.tokens == TokenUsage(
        prompt=1_000_000, completion=0, reasoning=0, total=1_000_000
    )
    assert rec.cost.usd == 0.75 and rec.ms == 50  # gpt-5.4-mini input 0.75 $/Mtok


def test_cost_summary_totals_and_marks_unpriced():
    tele = _Telemetry(on_event=None, provider="openai")
    tele.done(
        "plan",
        "Planning",
        {},
        usage_sink=[LlmCallUsage("gpt-5.4-mini", 1_000_000, 0, 0, 1_000_000)],
        started=0.0,
        now=lambda: 0.0,
    )
    tele.done(
        "synth",
        "Synth",
        {},
        usage_sink=[LlmCallUsage("unknown", 1_000_000, 0, 0, 1_000_000)],
        started=0.0,
        now=lambda: 0.0,
    )
    cs = tele.cost_summary()
    assert cs.usd is None  # one call unpriced → no honest total
    assert cs.llm_calls == 2 and cs.tokens.prompt == 2_000_000


def test_non_llm_phase_has_no_tokens():
    events = []
    tele = _Telemetry(on_event=events.append, provider="openai")
    tele.done(
        "retrieve",
        "Retrieving",
        {"chunk_count": 3},
        usage_sink=[],
        started=0.0,
        now=lambda: 0.0,
    )
    assert events[0].tokens is None and events[0].cost is None
