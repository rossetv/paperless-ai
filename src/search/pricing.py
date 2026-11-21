"""Model-price table and the per-call cost calculator.

A local (Ollama) provider prices to $0 with ``local=True``; an unknown model
prices to ``usd=None`` (the UI shows "—") rather than a wrong figure.

Reasoning tokens are a subset of completion tokens (they bill as output), so the
cost uses ``completion`` alone, never completion + reasoning.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from search.models import Cost, TokenUsage


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD price per million tokens, input and output."""

    input_per_mtok: float
    output_per_mtok: float


# OpenAI list prices, USD per 1M tokens — Standard tier, short context
# (https://openai.com/api/pricing). 5.4-era rows confirmed on 2026-06-10, 5.6
# rows on 2026-07-14. Ollama models are absent: the provider check prices them
# as free.
#
# Cached-input discounts are not modelled: every prompt token is priced at the
# full input rate, a deliberate small over-estimate. The synthesiser's input is
# dominated by uncacheable retrieved chunks, so the overshoot is minor.
#
# The search path never uses Flex, so Flex pricing is not modelled either.
MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5.6-sol": ModelPrice(input_per_mtok=5.0, output_per_mtok=30.0),
    "gpt-5.6-terra": ModelPrice(input_per_mtok=2.5, output_per_mtok=15.0),
    "gpt-5.6-luna": ModelPrice(input_per_mtok=1.0, output_per_mtok=6.0),
    "gpt-5.5": ModelPrice(input_per_mtok=5.0, output_per_mtok=30.0),
    "gpt-5.4": ModelPrice(input_per_mtok=2.5, output_per_mtok=15.0),
    "gpt-5.4-mini": ModelPrice(input_per_mtok=0.75, output_per_mtok=4.5),
    "gpt-5.4-nano": ModelPrice(input_per_mtok=0.2, output_per_mtok=1.25),
    "o4-mini": ModelPrice(input_per_mtok=1.1, output_per_mtok=4.4),
}

# When MODEL_PRICES was last confirmed; the price book stamps its bundled seed
# with it. Update it together with the table.
SEED_PRICES_AS_OF: str = "2026-07-14"


def price_call(
    model: str,
    provider: str,
    usage: TokenUsage,
    *,
    table: Mapping[str, ModelPrice],
) -> Cost:
    """Price one call's *usage*. Local provider → $0/local; unknown model → None.

    *provider* is the endpoint that served this call, so a mixed-provider query
    prices each call correctly. ``table`` has no default so a caller cannot
    silently price against the bundled seed instead of the live price book.
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
