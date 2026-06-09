"""Tests for search.pricing — the model-price table and per-call cost calculator."""

from search.models import Cost, TokenUsage
from search.pricing import MODEL_PRICES, ModelPrice, price_call


def test_prices_a_known_openai_model():
    # input 1.0 $/Mtok, output 4.0 $/Mtok hypothetical
    price = ModelPrice(input_per_mtok=1.0, output_per_mtok=4.0)
    usage = TokenUsage(
        prompt=1_000_000, completion=500_000, reasoning=100_000, total=1_500_000
    )
    # cost = 1.0 + 0.5*4.0 = 3.0; reasoning is INSIDE completion, not added
    got = price_call("m", "openai", usage, table={"m": price})
    assert got == Cost(usd=3.0, local=False)


def test_ollama_is_local_zero():
    got = price_call("gemma3:12b", "ollama", TokenUsage(10, 20, 0, 30), table={})
    assert got == Cost(usd=0.0, local=True)


def test_unknown_openai_model_is_unpriced():
    got = price_call("mystery", "openai", TokenUsage(10, 20, 0, 30), table={})
    assert got == Cost(usd=None, local=False)


def test_default_table_is_populated_and_typed():
    assert isinstance(MODEL_PRICES, dict)
    assert all(isinstance(v, ModelPrice) for v in MODEL_PRICES.values())
