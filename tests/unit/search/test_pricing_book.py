"""Tests for search.pricing_book — the seed/cache/refresh model-price book.

The headline contract this proves:

- **Behaviour-preserving default.** ``seed_price_book()`` yields exactly
  ``MODEL_PRICES`` with ``as_of == SEED_PRICES_AS_OF`` and ``source == "bundled"``,
  prices the identical dollars ``price_call`` produced against the bare constant
  for every prod model, and touches no network.
- **Cache mapping.** ``price_book_from_cache`` maps app.db floats to ModelPrice
  and carries provenance through; ``to_cached_table`` is its inverse.
- **Refresh.** ``refresh_price_book`` parses a valid USD payload into the right
  table/as_of/source on a bounded timeout, and raises ``PricingRefreshError`` on
  non-200, malformed JSON, missing/negative/non-numeric prices, and non-USD
  currency.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from appdb.model_pricing import CachedModelPrice, CachedPriceBook
from search.models import TokenUsage
from search.pricing import MODEL_PRICES, SEED_PRICES_AS_OF, ModelPrice, price_call
from search.pricing_book import (
    BUNDLED_SOURCE,
    DEFAULT_REFRESH_TIMEOUT_SECONDS,
    PriceBook,
    PricingRefreshError,
    get_current_price_book,
    price_book_from_cache,
    refresh_price_book,
    reset_current_price_book,
    seed_price_book,
    set_current_price_book,
    to_cached_table,
)

_URL = "https://prices.example/openai.json"

# Every model in the prod search chain — the seed-path dollar figures must match
# the bare-constant figures for each.
_PROD_MODELS = ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "o4-mini"]


def _valid_payload() -> dict:
    """A schema-valid USD refresh payload covering two models."""
    return {
        "as_of": "2026-07-01",
        "currency": "USD",
        "models": {
            "gpt-5.5": {"input_per_mtok": 6.0, "output_per_mtok": 32.0},
            "gpt-5.4-mini": {"input_per_mtok": 0.8, "output_per_mtok": 5.0},
        },
    }


# --------------------------------------------------------------------------- #
# Behaviour-preserving seed path
# --------------------------------------------------------------------------- #


def test_seed_book_equals_the_bundled_table_with_bundled_provenance() -> None:
    book = seed_price_book()
    assert book.table == MODEL_PRICES
    assert book.as_of == SEED_PRICES_AS_OF
    assert book.source == BUNDLED_SOURCE
    assert book.is_bundled is True


def test_seed_book_table_is_a_copy_not_the_module_constant() -> None:
    """Mutating the book's table must not corrupt the shared module seed."""
    book = seed_price_book()
    book.table.pop("gpt-5.5", None)
    assert "gpt-5.5" in MODEL_PRICES  # the constant is untouched


@pytest.mark.parametrize("model", _PROD_MODELS)
def test_seed_book_prices_identical_dollars_to_the_bare_constant(model: str) -> None:
    """price_call against book.table == price_call against MODEL_PRICES exactly."""
    usage = TokenUsage(
        prompt=1_234_567, completion=890_123, reasoning=42_000, total=2_124_690
    )
    via_book = price_call(model, "openai", usage, table=seed_price_book().table)
    via_constant = price_call(model, "openai", usage, table=MODEL_PRICES)
    assert via_book == via_constant
    assert via_book.usd is not None  # a prod model is priced, not None


def test_building_the_seed_book_makes_no_network_call() -> None:
    """The default path is provably network-free: respx asserts zero requests."""
    with respx.mock(assert_all_mocked=True) as mock:
        # No routes registered: any outbound HTTP would raise, failing the test.
        book = seed_price_book()
        # effective_table() is the surface PART 2 wires into price_call.
        assert book.effective_table() == MODEL_PRICES
        assert mock.calls.call_count == 0


# --------------------------------------------------------------------------- #
# Cache mapping
# --------------------------------------------------------------------------- #


def test_price_book_from_cache_maps_floats_and_carries_provenance() -> None:
    cached = CachedPriceBook(
        table={
            "gpt-5.5": CachedModelPrice(input_per_mtok=5.0, output_per_mtok=30.0),
            "o4-mini": CachedModelPrice(input_per_mtok=1.1, output_per_mtok=4.4),
        },
        as_of="2026-06-10",
        source=_URL,
        fetched_at="2026-06-12T00:00:00+00:00",
    )

    book = price_book_from_cache(cached)

    assert book.table == {
        "gpt-5.5": ModelPrice(input_per_mtok=5.0, output_per_mtok=30.0),
        "o4-mini": ModelPrice(input_per_mtok=1.1, output_per_mtok=4.4),
    }
    assert book.as_of == "2026-06-10"
    assert book.source == _URL
    assert book.fetched_at == "2026-06-12T00:00:00+00:00"
    assert book.is_bundled is False


def test_to_cached_table_is_the_inverse_mapping() -> None:
    """A seed book round-trips through to_cached_table → price_book_from_cache."""
    book = seed_price_book()
    cached = CachedPriceBook(
        table=to_cached_table(book),
        as_of=book.as_of,
        source=book.source,
        fetched_at=book.fetched_at,
    )
    assert price_book_from_cache(cached).table == book.table


# --------------------------------------------------------------------------- #
# Refresh — success
# --------------------------------------------------------------------------- #


def test_refresh_parses_a_valid_payload_into_a_book() -> None:
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=_valid_payload()))
        book = refresh_price_book(_URL)

    assert book.source == _URL
    assert book.is_bundled is False
    assert book.as_of == "2026-07-01"
    assert book.table == {
        "gpt-5.5": ModelPrice(input_per_mtok=6.0, output_per_mtok=32.0),
        "gpt-5.4-mini": ModelPrice(input_per_mtok=0.8, output_per_mtok=5.0),
    }


def test_refresh_passes_a_bounded_timeout() -> None:
    """The fetch carries a finite timeout (no unbounded wait, §8.7)."""
    seen: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json=_valid_payload())

    with respx.mock:
        respx.get(_URL).mock(side_effect=_capture)
        refresh_price_book(_URL, timeout=3.5)

    # httpx maps a float timeout onto every phase; each must be the bound, never
    # None (unbounded).
    timeout = seen["timeout"]
    assert isinstance(timeout, dict)
    assert set(timeout.values()) == {3.5}
    # And the default is itself finite.
    assert DEFAULT_REFRESH_TIMEOUT_SECONDS > 0


# --------------------------------------------------------------------------- #
# Refresh — failure modes (all raise PricingRefreshError)
# --------------------------------------------------------------------------- #


def test_refresh_raises_on_non_200() -> None:
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(503, text="down"))
        with pytest.raises(PricingRefreshError):
            refresh_price_book(_URL)


def test_refresh_raises_on_transport_error() -> None:
    with respx.mock:
        respx.get(_URL).mock(side_effect=httpx.ConnectError("no route"))
        with pytest.raises(PricingRefreshError):
            refresh_price_book(_URL)


def test_refresh_raises_on_malformed_json() -> None:
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, text="this is not json"))
        with pytest.raises(PricingRefreshError):
            refresh_price_book(_URL)


def test_refresh_raises_on_non_usd_currency() -> None:
    payload = _valid_payload()
    payload["currency"] = "EUR"
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(PricingRefreshError, match="currency"):
            refresh_price_book(_URL)


def test_refresh_raises_on_missing_currency() -> None:
    payload = _valid_payload()
    del payload["currency"]
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(PricingRefreshError):
            refresh_price_book(_URL)


def test_refresh_raises_on_empty_models() -> None:
    payload = _valid_payload()
    payload["models"] = {}
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(PricingRefreshError):
            refresh_price_book(_URL)


def test_refresh_raises_on_missing_price_field() -> None:
    payload = _valid_payload()
    del payload["models"]["gpt-5.5"]["output_per_mtok"]
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(PricingRefreshError, match="output_per_mtok"):
            refresh_price_book(_URL)


def test_refresh_raises_on_negative_price() -> None:
    payload = _valid_payload()
    payload["models"]["gpt-5.5"]["input_per_mtok"] = -1.0
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(PricingRefreshError, match="input_per_mtok"):
            refresh_price_book(_URL)


def test_refresh_raises_on_non_numeric_price() -> None:
    payload = _valid_payload()
    payload["models"]["gpt-5.5"]["input_per_mtok"] = "free"
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(PricingRefreshError):
            refresh_price_book(_URL)


def test_refresh_raises_on_boolean_price() -> None:
    """A JSON true must not sneak through as 1.0 (bool is an int subclass)."""
    payload = _valid_payload()
    payload["models"]["gpt-5.5"]["input_per_mtok"] = True
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(PricingRefreshError):
            refresh_price_book(_URL)


def test_refresh_raises_on_missing_as_of() -> None:
    payload = _valid_payload()
    del payload["as_of"]
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(PricingRefreshError, match="as_of"):
            refresh_price_book(_URL)


def test_refresh_raises_on_non_object_payload() -> None:
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(200, json=[1, 2, 3]))
        with pytest.raises(PricingRefreshError):
            refresh_price_book(_URL)


# --------------------------------------------------------------------------- #
# PriceBook surface
# --------------------------------------------------------------------------- #


def test_effective_table_returns_the_table() -> None:
    book = PriceBook(
        table={"m": ModelPrice(1.0, 4.0)},
        as_of="2026-01-01",
        source="bundled",
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    assert book.effective_table() == {"m": ModelPrice(1.0, 4.0)}


# --------------------------------------------------------------------------- #
# Current-price-book singleton (PART 2)
# --------------------------------------------------------------------------- #


def _other_book() -> PriceBook:
    """A distinct, non-seed book for asserting a swap took effect."""
    return PriceBook(
        table={"gpt-5.5": ModelPrice(input_per_mtok=9.0, output_per_mtok=99.0)},
        as_of="2099-12-31",
        source=_URL,
        fetched_at="2099-12-31T00:00:00+00:00",
    )


def test_current_price_book_defaults_to_the_seed() -> None:
    """Untouched, the live book IS the bundled seed — the no-config default."""
    reset_current_price_book()
    book = get_current_price_book()
    assert book.source == BUNDLED_SOURCE
    assert book.as_of == SEED_PRICES_AS_OF
    assert book.table == MODEL_PRICES


def test_set_current_price_book_publishes_the_new_book() -> None:
    """A set is visible to the next get — the refresh task's publish path."""
    reset_current_price_book()
    other = _other_book()
    set_current_price_book(other)
    try:
        live = get_current_price_book()
        assert live.source == _URL
        assert live.as_of == "2099-12-31"
        assert live.table["gpt-5.5"] == ModelPrice(9.0, 99.0)
    finally:
        reset_current_price_book()


def test_reset_current_price_book_restores_the_seed() -> None:
    """reset() returns a fresh seed book, discarding any prior swap."""
    set_current_price_book(_other_book())
    reset_current_price_book()
    assert get_current_price_book().source == BUNDLED_SOURCE
    assert get_current_price_book().table == MODEL_PRICES
