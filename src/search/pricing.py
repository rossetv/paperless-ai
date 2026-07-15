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

from collections.abc import Mapping
from dataclasses import dataclass

from search.models import Cost, TokenUsage


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD price per million tokens, input and output."""

    input_per_mtok: float
    output_per_mtok: float


# OpenAI list prices, USD per 1M tokens — Standard tier, short context
# (https://openai.com/api/pricing). THE single edit point when rates change.
# 5.4-era rows confirmed against the operator's account on 2026-06-10; covers
# the prod search chain (planner/judge gpt-5.4-nano, answer gpt-5.4-mini, and
# the gpt-5.4-mini/gpt-5.4/gpt-5.5/o4-mini fallback). 5.6 rows taken from the
# live pricing docs on 2026-07-14. Ollama/local models are intentionally absent
# (priced as free via the provider check, not this table).
#
# Cached-input discounts are NOT modelled: every prompt token is priced at the
# full (uncached) input rate. OpenAI bills cache-hit prompt tokens at a lower
# rate, so this is a small, deliberately conservative OVER-estimate, never an
# under-count. The cache-optimised system prompts make some hits likely, but the
# synthesiser's input is dominated by the (uncacheable) retrieved chunks, so the
# overshoot is minor.
#
# Flex halves the actual OCR/classifier spend, but this table prices only the
# search path, which never uses Flex — no Flex modelling needed.
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

# The date :data:`MODEL_PRICES` was last confirmed against the operator's
# OpenAI account (the comment above). Carried as a named constant so the price
# book (:mod:`search.pricing_book`) can stamp the bundled-seed book's ``as_of``
# from the single source of truth here rather than re-typing the date — when
# the seed table is updated, this date moves with it in the same edit.
SEED_PRICES_AS_OF: str = "2026-07-14"


def price_call(
    model: str,
    provider: str,
    usage: TokenUsage,
    *,
    table: Mapping[str, ModelPrice],
) -> Cost:
    """Price one call's *usage*. Local provider → $0/local; unknown model → None.

    *provider* is the endpoint that actually served this call (the model's
    routed provider, from :attr:`~common.llm.LlmCallUsage.provider`), so a
    mixed-provider query prices each call against the right table — a local
    (Ollama) call is free even when other steps ran on OpenAI, and vice versa.

    ``table`` is required — the caller always passes the live price book's
    effective table (:meth:`~search.pricing_book.PriceBook.effective_table`);
    tests pass :data:`MODEL_PRICES` explicitly. Defaulting it would silently let
    a caller price against the stale bundled seed instead of the live book.
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
