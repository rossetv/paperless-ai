"""The cached, refreshable model-price book in the application database.

This module owns the :class:`CachedModelPrice` and :class:`CachedPriceBook`
dataclasses and the typed query functions over the ``model_pricing`` table
(``app.db`` migration v8). It is the persistence half of the price book: the
:mod:`search.pricing_book` layer seeds, refreshes, and maps these rows to its
own :class:`~search.pricing.ModelPrice` shape, while this module only stores and
loads plain USD floats keyed by model name plus the provenance of the cache.

``appdb`` sits below ``search`` and may not import it (CODE_GUIDELINES §2.2.1),
so the boundary here is deliberately ``search``-free — plain ``float`` prices in
a ``dict[str, CachedModelPrice]``. The search layer maps these to its own
``ModelPrice`` at its own boundary.

Two behaviours worth stating:

- **Atomic replace.** :func:`save_cached_prices` replaces the whole cache —
  ``DELETE`` every row, then re-``INSERT`` the new set — inside one
  ``BEGIN IMMEDIATE`` transaction, so a concurrent reader never sees a
  half-written cache and a mid-write failure leaves the prior cache intact.
- **Empty means none.** :func:`load_cached_prices` returns ``None`` (not an
  empty book) when the table holds no rows, so the caller can fall back to the
  bundled seed and tell "never refreshed" apart from "refreshed to an empty
  table" (the latter is rejected upstream before it can be saved).

Allowed deps: sqlite3, structlog, appdb.connection. Forbidden: store, search,
common, daemon packages, FastAPI.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import structlog

from appdb.connection import transaction

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CachedModelPrice:
    """One model's USD list price per million tokens, as stored in ``app.db``.

    Frozen: a loaded row is a snapshot, never mutated in place. Deliberately a
    plain-float mirror of :class:`search.pricing.ModelPrice` — ``appdb`` cannot
    import ``search``, so the search layer maps between the two at its boundary.

    Attributes:
        input_per_mtok: USD price per one million prompt (input) tokens.
        output_per_mtok: USD price per one million completion (output) tokens.
    """

    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True, slots=True)
class CachedPriceBook:
    """The whole cached price book loaded from ``app.db``: prices + provenance.

    Frozen snapshot of one consistent cache state. ``table`` maps each model
    name to its :class:`CachedModelPrice`; the three provenance fields describe
    where this cache came from and when, shared by every row (the cache is
    replaced atomically, so there is never a mixed-provenance state).

    Attributes:
        table: Model name → :class:`CachedModelPrice`. Non-empty: a loaded book
            always carries at least one row (an empty cache loads as ``None``).
        as_of: The price list's own effective date (``YYYY-MM-DD``).
        source: Provenance — the literal ``"bundled"`` for the seed, or the
            refresh URL the prices were fetched from.
        fetched_at: ISO-8601 UTC timestamp the cache was last written.
    """

    table: dict[str, CachedModelPrice]
    as_of: str
    source: str
    fetched_at: str


def load_cached_prices(conn: sqlite3.Connection) -> CachedPriceBook | None:
    """Return the cached price book, or ``None`` when the cache is empty.

    Reads every ``model_pricing`` row in one query. ``None`` (rather than an
    empty book) signals "the cache has never been written" so the caller falls
    back to the bundled seed; the provenance is taken from the first row, which
    is safe because :func:`save_cached_prices` writes one consistent
    ``(as_of, source, fetched_at)`` across every row in a single transaction.

    Args:
        conn: An open, migrated ``app.db`` connection.

    Returns:
        The cached :class:`CachedPriceBook`, or ``None`` when no rows exist.
    """
    rows = conn.execute(
        "SELECT model, input_per_mtok, output_per_mtok, as_of, source, fetched_at "
        "FROM model_pricing "
        "ORDER BY model"
    ).fetchall()
    if not rows:
        return None
    table = {
        row["model"]: CachedModelPrice(
            input_per_mtok=row["input_per_mtok"],
            output_per_mtok=row["output_per_mtok"],
        )
        for row in rows
    }
    first = rows[0]
    return CachedPriceBook(
        table=table,
        as_of=first["as_of"],
        source=first["source"],
        fetched_at=first["fetched_at"],
    )


def save_cached_prices(
    conn: sqlite3.Connection,
    *,
    table: dict[str, CachedModelPrice],
    as_of: str,
    source: str,
    fetched_at: str,
) -> None:
    """Replace the whole price cache with *table* and its shared provenance.

    The replace is atomic: every existing row is deleted and the new set
    inserted inside one ``BEGIN IMMEDIATE`` transaction, so a concurrent reader
    sees either the old cache or the new one — never a partial mix — and a
    mid-write failure rolls back to the prior cache intact. The same
    ``(as_of, source, fetched_at)`` is stamped on every row so a later
    :func:`load_cached_prices` reads one consistent provenance.

    Args:
        conn: An open, migrated ``app.db`` connection.
        table: Model name → :class:`CachedModelPrice` to persist. May be empty,
            though callers reject an empty refresh before reaching here.
        as_of: The price list's effective date (``YYYY-MM-DD``).
        source: Provenance — ``"bundled"`` or the refresh URL.
        fetched_at: ISO-8601 UTC timestamp of this write.
    """
    with transaction(conn):
        conn.execute("DELETE FROM model_pricing")
        conn.executemany(
            "INSERT INTO model_pricing "
            "(model, input_per_mtok, output_per_mtok, as_of, source, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    model,
                    price.input_per_mtok,
                    price.output_per_mtok,
                    as_of,
                    source,
                    fetched_at,
                )
                for model, price in table.items()
            ],
        )
    log.info(
        "appdb.model_pricing_saved",
        model_count=len(table),
        source=source,
        as_of=as_of,
    )
