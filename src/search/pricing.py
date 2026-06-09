"""Editable model-price table and the per-call cost calculator (spec §Pricing).

Prices are facts, not per-deployment preferences, so they live here as a code
constant — the single edit point when OpenAI changes rates. Tokens are always
captured exactly; a dollar cost is shown only for a priced model. A local
(Ollama) provider is genuinely free, so it prices to $0 with ``local=True``; an
unknown model prices to ``usd=None`` (the UI shows "—") rather than a wrong
figure.

Reasoning tokens are a SUBSET of completion tokens (they bill as output), so the
cost uses ``completion`` alone — never completion + reasoning.

Allowed deps: search.models. Forbidden: config, I/O, network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from search.models import Cost, TokenUsage


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD price per million tokens, input and output."""

    input_per_mtok: float
    output_per_mtok: float


# Current OpenAI list prices (USD / 1M tokens). THE single edit point — update
# when rates change. Ollama/local models are intentionally absent (priced as
# free via the provider check, not this table).
MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5.5": ModelPrice(input_per_mtok=1.25, output_per_mtok=10.0),
    "gpt-5.4": ModelPrice(input_per_mtok=1.0, output_per_mtok=8.0),
    "gpt-5.4-mini": ModelPrice(input_per_mtok=0.25, output_per_mtok=2.0),
}


def price_call(
    model: str,
    provider: str,
    usage: TokenUsage,
    *,
    table: Mapping[str, ModelPrice] = MODEL_PRICES,
) -> Cost:
    """Price one call's *usage*. Local provider → $0/local; unknown model → None.

    ``table`` is injectable for tests; production uses :data:`MODEL_PRICES`.
    """
    if provider == "ollama":
        return Cost(usd=0.0, local=True)
    price = table.get(model)
    if price is None:
        return Cost(usd=None, local=False)
    usd = (usage.prompt / 1_000_000) * price.input_per_mtok + (
        usage.completion / 1_000_000
    ) * price.output_per_mtok
    return Cost(usd=usd, local=False)
