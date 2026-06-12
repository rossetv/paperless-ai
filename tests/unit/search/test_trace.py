"""Tests for the _Telemetry accumulator and phase events in search.trace (Task 4)."""

from search.models import LlmCallUsage, PhaseRecord, TokenUsage
from search.pricing import SEED_PRICES_AS_OF, ModelPrice
from search.pricing_book import (
    BUNDLED_SOURCE,
    PriceBook,
    reset_current_price_book,
    set_current_price_book,
)
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


# --------------------------------------------------------------------------- #
# Price-book provenance (PART 2)
# --------------------------------------------------------------------------- #


def test_cost_summary_carries_seed_provenance_by_default():
    """With no book injected, the telemetry reports the live (seed) provenance."""
    reset_current_price_book()
    tele = _Telemetry(on_event=None, provider="openai")
    cs = tele.cost_summary()
    assert cs.prices_source == BUNDLED_SOURCE
    assert cs.prices_as_of == SEED_PRICES_AS_OF


def test_telemetry_prices_against_the_live_book_by_default():
    """A swapped-in live book changes the dollars the default telemetry computes."""
    reset_current_price_book()
    # 2 $/Mtok input — distinct from the seed's gpt-5.4-mini (0.75) so the swap
    # is observable in the dollar figure.
    set_current_price_book(
        PriceBook(
            table={"gpt-5.4-mini": ModelPrice(input_per_mtok=2.0, output_per_mtok=8.0)},
            as_of="2099-01-01",
            source="https://prices.example/openai.json",
            fetched_at="2099-01-01T00:00:00+00:00",
        )
    )
    try:
        tele = _Telemetry(on_event=None, provider="openai")
        tele.done(
            "plan",
            "Planning",
            {},
            usage_sink=[LlmCallUsage("gpt-5.4-mini", 1_000_000, 0, 0, 1_000_000)],
            started=0.0,
            now=lambda: 0.0,
        )
        cs = tele.cost_summary()
        assert cs.usd == 2.0  # 1 Mtok input × 2 $/Mtok, the swapped-in rate
        assert cs.prices_source == "https://prices.example/openai.json"
        assert cs.prices_as_of == "2099-01-01"
    finally:
        reset_current_price_book()


def test_injected_book_overrides_the_live_book_for_determinism():
    """An explicit price_book is used verbatim, ignoring the live singleton."""
    # Set a different live book to prove the injected one wins.
    set_current_price_book(
        PriceBook(
            table={"gpt-5.4-mini": ModelPrice(99.0, 99.0)},
            as_of="2000-01-01",
            source="ignored",
            fetched_at="2000-01-01T00:00:00+00:00",
        )
    )
    try:
        injected = PriceBook(
            table={"gpt-5.4-mini": ModelPrice(input_per_mtok=1.0, output_per_mtok=4.0)},
            as_of="2030-06-06",
            source="injected-source",
            fetched_at="2030-06-06T00:00:00+00:00",
        )
        tele = _Telemetry(on_event=None, provider="openai", price_book=injected)
        tele.done(
            "plan",
            "Planning",
            {},
            usage_sink=[LlmCallUsage("gpt-5.4-mini", 1_000_000, 0, 0, 1_000_000)],
            started=0.0,
            now=lambda: 0.0,
        )
        cs = tele.cost_summary()
        assert cs.usd == 1.0  # the injected rate, not the live 99.0
        assert cs.prices_source == "injected-source"
        assert cs.prices_as_of == "2030-06-06"
    finally:
        reset_current_price_book()
