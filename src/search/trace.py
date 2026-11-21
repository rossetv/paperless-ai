"""Per-request search telemetry: phase events plus token/cost accumulation.

One ``_Telemetry`` per :meth:`SearchCore.answer` call emits a
:class:`PhaseStart` + :class:`PhaseRecord` pair per phase to the optional
``on_event`` sink and accumulates the whole-query :class:`CostSummary`.
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

    The price book is resolved once, at construction, so a background refresh
    mid-search cannot split the pricing across two tables and the reported
    provenance matches the dollars computed.

    Each call is priced against the provider on its own
    :class:`~common.llm.LlmCallUsage`, so a mixed-provider query (e.g. the judge
    on Ollama, the rest on OpenAI) costs each step correctly.
    """

    def __init__(
        self,
        on_event: OnEvent | None,
        *,
        price_book: PriceBook | None = None,
    ) -> None:
        self._on_event = on_event
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
        """Produce the whole-query cost summary, stamped with price provenance."""
        return CostSummary(
            tokens=self._tokens_total,
            usd=self._usd_total if self._usd_known else None,
            local=self._all_local,
            llm_calls=self._call_count,
            prices_as_of=self._price_book.as_of,
            prices_source=self._price_book.source,
        )
