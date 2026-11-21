"""Storage for the cached model-price book, the ``model_pricing`` table.

Plain USD floats keyed by model name; :mod:`search.pricing_book` seeds and
refreshes the cache and maps rows to its own ``ModelPrice``, since ``appdb``
cannot import ``search``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import structlog

from appdb.connection import transaction

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CachedModelPrice:
    """One model's USD list price per million input and output tokens."""

    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True, slots=True)
class CachedPriceBook:
    """The whole cached price book: prices plus the provenance every row shares.

    Attributes:
        as_of: The price list's own effective date (``YYYY-MM-DD``).
        source: ``"bundled"`` for the seed, or the refresh URL.
        fetched_at: ISO-8601 UTC timestamp the cache was last written.
    """

    table: dict[str, CachedModelPrice]
    as_of: str
    source: str
    fetched_at: str


def load_cached_prices(conn: sqlite3.Connection) -> CachedPriceBook | None:
    """Return the cached price book, or ``None`` when the cache is empty.

    ``None`` tells the caller to fall back to the bundled seed. Provenance is
    read from the first row; :func:`save_cached_prices` stamps the same values
    on every row.
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

    Delete-then-insert in one ``BEGIN IMMEDIATE`` transaction, so a reader sees
    the old cache or the new one, never a mix, and a failure keeps the old one.
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
