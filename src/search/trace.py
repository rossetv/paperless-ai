"""Per-request search telemetry: phase events + token/cost accumulation.

A ``_Telemetry`` instance is created once per :meth:`SearchCore.answer` call. It
turns each phase into a :class:`PhaseStart` + :class:`PhaseRecord` event pair
(forwarded to the optional ``on_event`` sink for live streaming), summarises that
phase's LLM token usage, prices it, and accumulates the whole-query
:class:`CostSummary`. The assembled :class:`SearchTrace` and ``CostSummary`` ride
on ``SearchStats`` so they are cacheable and reach every consumer.

Allowed deps: search.models, search.pricing, search.pricing_book. Forbidden:
I/O, FastAPI, LLM calls.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from common.llm import LlmCallUsage
from search.models import (
    Cost,
    CostSummary,
    PhaseRecord,
    SearchTrace,
    TokenUsage,
)
from search.pricing import price_call
from search.pricing_book import PriceBook, get_current_price_book


@dataclass(frozen=True, slots=True)
class PhaseStart:
    """Emitted when a phase begins, before its work runs."""

    phase: str
    label: str


#: What the ``on_event`` callback receives: a start marker, then the done record.
PhaseEvent = PhaseStart | PhaseRecord
OnEvent = Callable[[PhaseEvent], None]


def _sum_usage(sink: Sequence[LlmCallUsage]) -> TokenUsage:
    return TokenUsage(
        prompt=sum(u.prompt for u in sink),
        completion=sum(u.completion for u in sink),
        reasoning=sum(u.reasoning for u in sink),
        total=sum(u.total for u in sink),
    )


class _Telemetry:
    """Accumulates the trace + cost for one search, emitting events as it goes.

    The price book is resolved ONCE per search (at construction) — pinned for the
    request so every call is priced against a single consistent table even if a
    background refresh swaps the live book mid-search, and so the provenance the
    cost summary reports matches the dollars it computed.

    Each LLM call is priced against the provider recorded on its own
    :class:`~common.llm.LlmCallUsage` (the endpoint that actually served it),
    not a single telemetry-wide provider — so a mixed-provider query (e.g. the
    judge on Ollama while the planner and answer run on OpenAI) costs each step
    correctly instead of mispricing every call against one global provider.

    Args:
        on_event: Optional sink for live phase events (the streaming route). When
            None, the telemetry still assembles the trace/cost for the result.
        price_book: The price book to cost against. Defaults to the process-wide
            live book (:func:`~search.pricing_book.get_current_price_book`) —
            the bundled seed unless a cache/refresh replaced it. Injectable so
            unit tests stay deterministic against a known table.
    """

    def __init__(
        self,
        on_event: OnEvent | None,
        *,
        price_book: PriceBook | None = None,
    ) -> None:
        self._on_event = on_event
        # Resolve the live book once and pin it for the whole search (see the
        # class docstring). Tests inject a known book to stay deterministic.
        self._price_book = (
            price_book if price_book is not None else get_current_price_book()
        )
        self._phases: list[PhaseRecord] = []
        self._usd_total = 0.0
        self._usd_known = True  # flips False if any call is unpriced-and-not-local
        self._all_local = True
        self._call_count = 0
        self._tokens_total = TokenUsage(0, 0, 0, 0)

    def start(self, phase: str, label: str) -> None:
        """Emit a :class:`PhaseStart` event for the given phase."""
        if self._on_event is not None:
            self._on_event(PhaseStart(phase=phase, label=label))

    def done(
        self,
        phase: str,
        label: str,
        detail: dict[str, object],
        *,
        usage_sink: Sequence[LlmCallUsage],
        started: float,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """Record a completed phase: price its usage, emit, accumulate."""
        ms = int((now() - started) * 1000)
        if usage_sink:
            tokens = _sum_usage(usage_sink)
            cost = self._price_and_accumulate(usage_sink, tokens)
        else:
            tokens = None
            cost = None
        record = PhaseRecord(
            phase=phase, label=label, detail=detail, tokens=tokens, cost=cost, ms=ms
        )
        self._phases.append(record)
        if self._on_event is not None:
            self._on_event(record)

    def _price_and_accumulate(
        self, sink: Sequence[LlmCallUsage], phase_tokens: TokenUsage
    ) -> Cost:
        phase_usd: float | None = 0.0
        phase_local = True
        for call in sink:
            self._call_count += 1
            call_tokens = TokenUsage(
                call.prompt, call.completion, call.reasoning, call.total
            )
            cost = price_call(
                call.model,
                call.provider,
                call_tokens,
                table=self._price_book.effective_table(),
            )
            if not cost.local:
                phase_local = False
                self._all_local = False
            if cost.usd is None:
                self._usd_known = False
                phase_usd = None
            elif phase_usd is not None:
                phase_usd += cost.usd
            if cost.usd is not None:
                self._usd_total += cost.usd
        self._tokens_total = TokenUsage(
            self._tokens_total.prompt + phase_tokens.prompt,
            self._tokens_total.completion + phase_tokens.completion,
            self._tokens_total.reasoning + phase_tokens.reasoning,
            self._tokens_total.total + phase_tokens.total,
        )
        return Cost(usd=phase_usd, local=phase_local)

    def trace(self) -> SearchTrace:
        """Assemble the per-phase trace from accumulated records."""
        return SearchTrace(phases=tuple(self._phases))

    def cost_summary(self) -> CostSummary:
        """Produce the whole-query cost summary, stamped with price provenance.

        ``prices_as_of`` / ``prices_source`` carry the as-of date and source of
        the price book this search costed against (the pinned live book — the
        bundled seed unless a refresh replaced it), so the UI can show "prices as
        of <date>" alongside the dollar figure.
        """
        return CostSummary(
            tokens=self._tokens_total,
            usd=self._usd_total if self._usd_known else None,
            local=self._all_local,
            llm_calls=self._call_count,
            prices_as_of=self._price_book.as_of,
            prices_source=self._price_book.source,
        )
