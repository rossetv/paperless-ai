"""The model-price book: bundled seed, app.db cache, and optional refresh.

The pure cost calculator lives in :mod:`search.pricing` and is forbidden config,
I/O, and network. This module is its I/O sibling: it assembles the
:class:`PriceBook` — the effective USD price table plus its provenance — from one
of three sources, in this precedence:

1. **bundled seed** — :data:`search.pricing.MODEL_PRICES` as of
   :data:`search.pricing.SEED_PRICES_AS_OF`. Always available, zero I/O, zero
   network. This is the behaviour-preserving default: with no refresh URL
   configured, the price book equals the bundled table exactly and prices the
   identical dollar figures the hardcoded constant produced.
2. **app.db cache** — a previously refreshed table persisted by
   :mod:`appdb.model_pricing`, so a refreshed price survives a restart.
3. **refresh fetch** — an OPTIONAL, operator-configured URL returning the JSON
   price schema below. Fetched on a bounded timeout; on ANY failure a typed
   :class:`PricingRefreshError` is raised and the caller keeps the prior book.

**There is no official OpenAI pricing API.** OpenAI's ``/v1/models`` returns
models, not prices, so "fetch live prices from OpenAI" is not possible. The
refresh source is therefore an operator-provided URL — a self-hosted or
community-maintained price list the operator trusts and points the deployment
at. No third-party URL is baked in as a default; the feature is disabled (seed
only) unless the operator configures one.

The refresh JSON schema (this is the contract a refresh URL must serve)::

    {
      "as_of": "YYYY-MM-DD",
      "currency": "USD",
      "models": {
        "gpt-5.5":      {"input_per_mtok": 5.0, "output_per_mtok": 30.0},
        "gpt-5.4-mini": {"input_per_mtok": 0.75, "output_per_mtok": 4.5}
      }
    }

Only ``USD`` is supported — a non-USD ``currency`` is rejected, because the UI
shows a dollar figure and silently treating another currency as dollars would
be wrong. ``as_of`` must be a ``YYYY-MM-DD`` string; ``models`` must be a
non-empty object whose every entry carries finite, non-negative ``input_per_mtok``
and ``output_per_mtok`` numbers. Any violation raises
:class:`PricingRefreshError`.

This is PART 1 (the data layer). Wiring the book into the live trace, the cost
summary, and a background refresh task is PART 2 — this module only provides the
public surface (:func:`seed_price_book`, :func:`price_book_from_cache`,
:func:`refresh_price_book`, and :meth:`PriceBook.effective_table`).

Allowed deps: httpx, structlog, search.pricing, appdb.model_pricing. The price
table this builds is consumed by :func:`search.pricing.price_call` via
``table=book.effective_table()``; the calculator itself stays pure.
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

# The provenance value stamped on the bundled-seed book. The app.db cache stores
# this string verbatim in its ``source`` column for a seed-sourced cache; a
# refreshed cache stores the refresh URL instead, so the two are distinguishable.
BUNDLED_SOURCE: str = "bundled"

# The only currency the price book understands. The UI renders a USD dollar
# figure, so a refresh payload in any other currency is rejected rather than
# silently mis-priced (see the module docstring).
SUPPORTED_CURRENCY: str = "USD"

# Default bound on the refresh HTTP fetch, in seconds. Every outbound call has a
# timeout (CODE_GUIDELINES §8.7); the refresh is a best-effort background job, so
# a slow or hung price-list host must not block the caller indefinitely. Callers
# may override via ``refresh_price_book(url, timeout=...)``.
DEFAULT_REFRESH_TIMEOUT_SECONDS: float = 10.0


class PricingRefreshError(Exception):
    """A refresh fetch failed and the prior price book must be kept.

    Raised by :func:`refresh_price_book` for every failure mode — a network or
    connection error, a non-200 status, malformed JSON, a schema violation
    (wrong shape, non-USD currency, missing/negative/non-numeric price), or an
    empty model set. A single typed fault so the caller (PART 2) has one thing
    to catch: log it and continue serving the previous book rather than crash or
    serve a partial table (CODE_GUIDELINES §1.4, §6.1).
    """


@dataclass(frozen=True, slots=True)
class PriceBook:
    """The effective model-price table plus where it came from and when.

    Frozen snapshot built by one of :func:`seed_price_book`,
    :func:`price_book_from_cache`, or :func:`refresh_price_book`. The pipeline
    prices a call with ``price_call(model, provider, usage,
    table=book.effective_table())`` — the table maps to
    :class:`~search.pricing.ModelPrice`, exactly the shape ``price_call`` expects.

    Attributes:
        table: Model name → :class:`~search.pricing.ModelPrice` (USD per Mtok).
        as_of: The price list's effective date (``YYYY-MM-DD``).
        source: Provenance — :data:`BUNDLED_SOURCE` for the seed, or the refresh
            URL the prices were fetched from.
        fetched_at: ISO-8601 UTC timestamp this book's prices were obtained. For
            the seed this is the moment the seed book was built (the seed has no
            "fetch"); for a cache or refresh it is when the prices were fetched.
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
        """Return the table to pass as ``price_call(..., table=...)``.

        A thin, intention-revealing accessor: PART 2 reads
        ``book.effective_table()`` at the call site rather than reaching into
        ``book.table`` directly, so the contract with :func:`search.pricing.price_call`
        is named in one place.
        """
        return self.table


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``+00:00`` offset.

    A local copy of the timestamp shape ``appdb`` uses — ``search`` does not
    import ``appdb.connection``'s helper for one string, and the value is only
    ever round-tripped, never parsed back, so format drift is harmless.
    """
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def seed_price_book() -> PriceBook:
    """Build the bundled-seed price book — the zero-I/O, zero-network default.

    Returns a :class:`PriceBook` whose table is a copy of
    :data:`search.pricing.MODEL_PRICES`, ``as_of`` is
    :data:`search.pricing.SEED_PRICES_AS_OF`, and ``source`` is
    :data:`BUNDLED_SOURCE`. This is the behaviour-preserving fallback: with no
    refresh URL configured, the effective table equals the hardcoded constant
    exactly, so :func:`search.pricing.price_call` returns the identical dollar
    figures it did before this feature existed. Touches no database and makes no
    network call.
    """
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

    Maps each :class:`appdb.model_pricing.CachedModelPrice` (plain floats) to a
    :class:`~search.pricing.ModelPrice`, carrying the cache's provenance through
    unchanged. This is the ``appdb`` → ``search`` boundary mapping the cache
    store cannot do itself (``appdb`` may not import ``search``).

    Args:
        cached: A non-``None`` book from :func:`appdb.model_pricing.load_cached_prices`.

    Returns:
        The equivalent :class:`PriceBook`.
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

    The inverse of :func:`price_book_from_cache`'s table mapping — used by PART 2
    to hand a freshly refreshed book to
    :func:`appdb.model_pricing.save_cached_prices`, which takes plain-float
    :class:`~appdb.model_pricing.CachedModelPrice` values (it may not import
    ``search``). Lives here, on the ``search`` side of the boundary, because this
    is the only place that knows both shapes.
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
    """Fetch, validate, and parse a refresh URL into a new :class:`PriceBook`.

    Performs a single bounded-timeout HTTP GET against *url*, expects the JSON
    price schema documented in the module docstring, validates it strictly, and
    returns a :class:`PriceBook` whose ``source`` is *url*. The caller (PART 2)
    is expected to keep its previous book on failure.

    Args:
        url: The operator-configured price-list URL. Assumed already validated as
            an ``http``/``https`` URL by the config layer.
        timeout: Total HTTP timeout in seconds; defaults to
            :data:`DEFAULT_REFRESH_TIMEOUT_SECONDS`. Bounds connect, read, write,
            and pool waits so a hung host cannot block the caller.

    Returns:
        A validated :class:`PriceBook` sourced from *url*.

    Raises:
        PricingRefreshError: Any failure — transport error, non-200 status,
            malformed JSON, schema violation (wrong shape, non-USD currency,
            missing/negative/non-numeric price), or an empty model set.
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

    rationale (CODE_GUIDELINES §8.1): the three shared clients
    (``PaperlessClient``, the LLM wrapper, ``EmbeddingClient``) each own a
    specific upstream; a generic price-list GET is a fourth, distinct,
    operator-configured destination (§10.8), so a bounded one-shot
    ``httpx.Client`` here is the right fit rather than bending a shared client to
    a foreign host.

    Returns the parsed JSON (an ``Any`` — the shape is validated by
    :func:`_parse_payload`, not here). Every failure becomes a
    :class:`PricingRefreshError` so the caller has one type to catch.
    """
    # Any: httpx's .json() returns Any; the structural validation that narrows it
    # lives in _parse_payload, which rejects every non-conforming shape.
    try:
        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise PricingRefreshError(
            f"price refresh from {url} returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        # Connection, timeout, DNS, etc. — the transport failed.
        raise PricingRefreshError(f"price refresh from {url} failed: {exc}") from exc
    except ValueError as exc:
        # response.json() raises ValueError (json.JSONDecodeError subclasses it)
        # on a body that is not valid JSON.
        raise PricingRefreshError(
            f"price refresh from {url} returned invalid JSON"
        ) from exc


def _parse_payload(payload: Any, url: str) -> tuple[dict[str, ModelPrice], str]:
    """Validate a refresh *payload* and return its ``(table, as_of)``.

    Enforces the documented schema strictly — wrong top-level shape, non-USD
    currency, a non-string/empty ``as_of``, a missing or empty ``models`` object,
    or any per-model entry whose ``input_per_mtok`` / ``output_per_mtok`` is
    absent, non-numeric, negative, or non-finite — raising
    :class:`PricingRefreshError` naming the offending key (never the body) on
    any violation (CODE_GUIDELINES §1.11, §6.6).

    Args:
        payload: The decoded JSON from :func:`_fetch_payload`.
        url: The source URL, used only in error messages for context.

    Returns:
        ``(table, as_of)`` — the validated price table and its effective date.
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
    """Validate one ``models`` *entry* into a :class:`~search.pricing.ModelPrice`.

    Rejects a non-object entry and any input/output price that is absent,
    non-numeric, negative, or non-finite (NaN/inf) — raising
    :class:`PricingRefreshError` naming *model* and the bad field.
    """
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
    """The process-wide live price book the trace reads when pricing a call.

    Which prices a deployment uses is a property of the *process*, not of any
    request: the bundled seed, the app.db cache loaded at startup, or whatever a
    background refresh last fetched. So the live book is one module singleton —
    the documented lock-owning singleton CODE_GUIDELINES §8.5 sanctions, mirroring
    ``common.concurrency.llm_limiter`` and ``common.model_compat.model_compat_cache``
    — a module-level mutable guarded by an internal :class:`threading.Lock`,
    because the refresh task (one thread) publishes a new book that every request
    thread must then see.

    Defaults to :func:`seed_price_book` so a process that never loads a cache or
    starts a refresh prices against the bundled seed — the behaviour-preserving
    default, identical to the figures the hardcoded constant produced.
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


# The module singleton. Built at import with the seed book so the live book is
# always usable — startup load and background refresh only ever replace it.
_current_price_book = _CurrentPriceBook()


def get_current_price_book() -> PriceBook:
    """Return the process-wide live price book (the seed until one is set).

    The trace reads this once per search to price every call against the live
    table. With no refresh configured and no cache loaded, it is the bundled
    seed — zero I/O, zero network, byte-identical dollar figures to the
    hardcoded constant.
    """
    return _current_price_book.get()


def set_current_price_book(book: PriceBook) -> None:
    """Publish *book* as the process-wide live price book.

    Called by PART 2's startup cache load and the background refresh task to swap
    in a freshly loaded or fetched book; every subsequent search prices against
    it. Thread-safe — the refresh task publishes from its own thread while
    request threads read.
    """
    _current_price_book.set(book)


def reset_current_price_book() -> None:
    """Restore the bundled-seed live book. For test isolation only."""
    _current_price_book.reset()
