"""The model-price book: bundled seed, app.db cache, and optional refresh.

A :class:`PriceBook` is the effective USD price table plus its provenance, from
one of three sources:

1. the bundled seed, :data:`search.pricing.MODEL_PRICES` (the default);
2. the app.db cache (:mod:`appdb.model_pricing`), so a refresh survives restart;
3. an optional operator-configured refresh URL. On any failure
   :class:`PricingRefreshError` is raised and the caller keeps the prior book.

OpenAI has no pricing API (``/v1/models`` returns models, not prices), so the
refresh source is a price list the operator trusts. No default URL is baked in.

The refresh URL must serve::

    {
      "as_of": "YYYY-MM-DD",
      "currency": "USD",
      "models": {
        "gpt-6.2-sol": {"input_per_mtok": 2.0, "output_per_mtok": 10.0},
        "gpt-6-luna":  {"input_per_mtok": 0.1, "output_per_mtok": 0.5}
      }
    }

Only ``USD`` is accepted, since the UI shows a dollar figure. ``models`` must be
non-empty and every price finite and non-negative.
"""

from __future__ import annotations

import datetime as _datetime
import threading
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from appdb.model_pricing import CachedModelPrice, CachedPriceBook
from search.pricing import MODEL_PRICES, SEED_PRICES_AS_OF, ModelPrice

log = structlog.get_logger(__name__)

# Provenance of the seed book; a refreshed book's source is its URL instead.
BUNDLED_SOURCE: str = "bundled"

SUPPORTED_CURRENCY: str = "USD"

# A hung price-list host must not block the best-effort refresh indefinitely.
DEFAULT_REFRESH_TIMEOUT_SECONDS: float = 10.0


class PricingRefreshError(Exception):
    """A refresh failed (transport, status, JSON or schema); keep the prior book."""


@dataclass(frozen=True, slots=True)
class PriceBook:
    """The effective model-price table plus where it came from and when.

    Attributes:
        as_of: The price list's effective date (``YYYY-MM-DD``).
        source: :data:`BUNDLED_SOURCE` for the seed, else the refresh URL.
        fetched_at: ISO-8601 UTC time the prices were obtained; for the seed,
            when the book was built.
    """

    table: dict[str, ModelPrice]
    as_of: str
    source: str
    fetched_at: str

    @property
    def is_bundled(self) -> bool:
        """Whether this book is the bundled seed (its source is not a URL)."""
        return self.source == BUNDLED_SOURCE

    def effective_table(self) -> dict[str, ModelPrice]:
        """Return the table to pass as ``price_call(..., table=...)``."""
        return self.table


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``+00:00`` offset."""
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def seed_price_book() -> PriceBook:
    """Build the bundled-seed price book; no database or network access."""
    # Copy the dict so a caller cannot mutate the module-level seed via the book;
    # ModelPrice itself is frozen, so the values are safely shared.
    return PriceBook(
        table=dict(MODEL_PRICES),
        as_of=SEED_PRICES_AS_OF,
        source=BUNDLED_SOURCE,
        fetched_at=_utc_now_iso(),
    )


def price_book_from_cache(cached: CachedPriceBook) -> PriceBook:
    """Build a :class:`PriceBook` from a loaded ``app.db`` cache.

    The mapping lives here because ``appdb`` may not import ``search``.
    """
    table = {
        model: ModelPrice(
            input_per_mtok=price.input_per_mtok,
            output_per_mtok=price.output_per_mtok,
        )
        for model, price in cached.table.items()
    }
    return PriceBook(
        table=table,
        as_of=cached.as_of,
        source=cached.source,
        fetched_at=cached.fetched_at,
    )


def to_cached_table(book: PriceBook) -> dict[str, CachedModelPrice]:
    """Map a :class:`PriceBook`'s table to the ``appdb`` cache shape.

    The inverse of :func:`price_book_from_cache`, for
    :func:`appdb.model_pricing.save_cached_prices`.
    """
    return {
        model: CachedModelPrice(
            input_per_mtok=price.input_per_mtok,
            output_per_mtok=price.output_per_mtok,
        )
        for model, price in book.table.items()
    }


def refresh_price_book(
    url: str, *, timeout: float = DEFAULT_REFRESH_TIMEOUT_SECONDS
) -> PriceBook:
    """Fetch and strictly validate *url* into a new :class:`PriceBook`.

    *url* is assumed already validated as ``http``/``https`` by the config layer.

    Raises:
        PricingRefreshError: On any failure; the caller keeps its previous book.
    """
    payload = _fetch_payload(url, timeout)
    table, as_of = _parse_payload(payload, url)
    book = PriceBook(
        table=table,
        as_of=as_of,
        source=url,
        fetched_at=_utc_now_iso(),
    )
    log.info(
        "search.pricing_refreshed",
        source=url,
        model_count=len(table),
        as_of=as_of,
    )
    return book


def _fetch_payload(url: str, timeout: float) -> Any:
    """GET *url* on a bounded timeout and return the decoded JSON body.

    The shared HTTP clients each own one upstream, so this operator-configured
    host gets a one-shot request instead. The shape is checked by
    :func:`_parse_payload`.
    """
    try:
        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise PricingRefreshError(
            f"price refresh from {url} returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise PricingRefreshError(f"price refresh from {url} failed: {exc}") from exc
    except ValueError as exc:
        # json.JSONDecodeError subclasses ValueError.
        raise PricingRefreshError(
            f"price refresh from {url} returned invalid JSON"
        ) from exc


def _parse_payload(payload: Any, url: str) -> tuple[dict[str, ModelPrice], str]:
    """Validate a refresh *payload* and return its ``(table, as_of)``.

    Errors name the offending key, never the body.
    """
    if not isinstance(payload, dict):
        raise PricingRefreshError(f"price refresh from {url} is not a JSON object")

    currency = payload.get("currency")
    if currency != SUPPORTED_CURRENCY:
        raise PricingRefreshError(
            f"price refresh from {url} has unsupported currency {currency!r}; "
            f"only {SUPPORTED_CURRENCY} is supported"
        )

    as_of = payload.get("as_of")
    if not isinstance(as_of, str) or not as_of.strip():
        raise PricingRefreshError(
            f"price refresh from {url} has a missing or invalid 'as_of' date"
        )

    models = payload.get("models")
    if not isinstance(models, dict) or not models:
        raise PricingRefreshError(f"price refresh from {url} has no 'models' entries")

    table = {
        model: _parse_model_price(model, entry, url) for model, entry in models.items()
    }
    return table, as_of


def _parse_model_price(model: str, entry: Any, url: str) -> ModelPrice:
    """Validate one ``models`` *entry* into a :class:`~search.pricing.ModelPrice`."""
    if not isinstance(entry, dict):
        raise PricingRefreshError(
            f"price refresh from {url}: model {model!r} entry is not an object"
        )
    return ModelPrice(
        input_per_mtok=_parse_price_field(model, entry, "input_per_mtok", url),
        output_per_mtok=_parse_price_field(model, entry, "output_per_mtok", url),
    )


def _parse_price_field(
    model: str, entry: dict[str, Any], field: str, url: str
) -> float:
    """Validate one price *field* of a model *entry* to a finite, non-negative float.

    A ``bool`` is rejected explicitly: in Python ``bool`` is an ``int`` subclass,
    so a stray ``true`` would otherwise sail through as ``1.0``.
    """
    raw = entry.get(field)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise PricingRefreshError(
            f"price refresh from {url}: model {model!r} {field} "
            f"is missing or non-numeric"
        )
    price = float(raw)
    # NaN/inf would corrupt every cost computed against this table; reject them.
    if price < 0 or price != price or price in (float("inf"), float("-inf")):
        raise PricingRefreshError(
            f"price refresh from {url}: model {model!r} {field} "
            f"must be a finite, non-negative number, got {raw!r}"
        )
    return price


class _CurrentPriceBook:
    """The process-wide live price book, starting as the bundled seed.

    A lock-guarded singleton because the refresh task publishes from its own
    thread while request threads read.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._book: PriceBook = seed_price_book()

    def get(self) -> PriceBook:
        """Return the current live price book (the seed until one is set)."""
        with self._lock:
            return self._book

    def set(self, book: PriceBook) -> None:
        """Publish *book* as the new live price book for every subsequent call."""
        with self._lock:
            self._book = book

    def reset(self) -> None:
        """Restore the bundled-seed book. For test isolation only."""
        with self._lock:
            self._book = seed_price_book()


_current_price_book = _CurrentPriceBook()


def get_current_price_book() -> PriceBook:
    """Return the process-wide live price book (the seed until one is set)."""
    return _current_price_book.get()


def set_current_price_book(book: PriceBook) -> None:
    """Publish *book* as the process-wide live price book. Thread-safe."""
    _current_price_book.set(book)


def reset_current_price_book() -> None:
    """Restore the bundled-seed live book. For test isolation only."""
    _current_price_book.reset()
