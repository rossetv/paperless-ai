"""Tests for appdb.model_pricing — the cached, refreshable model-price book.

Covers the contract: save then load round-trips the table and its provenance;
an empty cache loads as None (so the caller falls back to the bundled seed); a
second save atomically replaces the whole cache rather than merging; a failing
save inside the transaction leaves the prior cache intact.
"""

from __future__ import annotations

import sqlite3

import pytest

from appdb.connection import connect
from appdb.model_pricing import (
    CachedModelPrice,
    CachedPriceBook,
    load_cached_prices,
    save_cached_prices,
)
from appdb.schema import ensure_schema


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection (schema_version 8 = model_pricing present)."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def _table() -> dict[str, CachedModelPrice]:
    """A small two-model price table for round-trip tests."""
    return {
        "gpt-5.5": CachedModelPrice(input_per_mtok=5.0, output_per_mtok=30.0),
        "gpt-5.4-mini": CachedModelPrice(input_per_mtok=0.75, output_per_mtok=4.5),
    }


def test_load_on_empty_cache_returns_none(conn: sqlite3.Connection) -> None:
    assert load_cached_prices(conn) is None


def test_save_then_load_round_trips_table_and_provenance(
    conn: sqlite3.Connection,
) -> None:
    save_cached_prices(
        conn,
        table=_table(),
        as_of="2026-06-10",
        source="https://prices.example/list.json",
        fetched_at="2026-06-12T00:00:00+00:00",
    )

    loaded = load_cached_prices(conn)

    assert loaded is not None
    assert loaded == CachedPriceBook(
        table=_table(),
        as_of="2026-06-10",
        source="https://prices.example/list.json",
        fetched_at="2026-06-12T00:00:00+00:00",
    )


def test_save_replaces_the_whole_cache_atomically(conn: sqlite3.Connection) -> None:
    save_cached_prices(
        conn,
        table=_table(),
        as_of="2026-06-10",
        source="bundled",
        fetched_at="2026-06-12T00:00:00+00:00",
    )

    # A second save with a disjoint, smaller table must wholly replace the first,
    # not merge — the dropped model must be gone.
    save_cached_prices(
        conn,
        table={"o4-mini": CachedModelPrice(input_per_mtok=1.1, output_per_mtok=4.4)},
        as_of="2026-07-01",
        source="https://prices.example/list.json",
        fetched_at="2026-07-01T00:00:00+00:00",
    )

    loaded = load_cached_prices(conn)
    assert loaded is not None
    assert set(loaded.table) == {"o4-mini"}
    assert loaded.as_of == "2026-07-01"
    assert loaded.source == "https://prices.example/list.json"


class _UnbindablePrice:
    """A price whose attributes sqlite cannot bind, to force an INSERT failure.

    A drop-in for CachedModelPrice carrying an ``object()`` sqlite has no
    adapter for, so the INSERT raises ``sqlite3.ProgrammingError`` *after* the
    DELETE has run inside the same transaction — the realistic mid-replace
    failure the rollback must survive.
    """

    input_per_mtok = object()
    output_per_mtok = object()


def test_failed_save_leaves_prior_cache_intact(conn: sqlite3.Connection) -> None:
    save_cached_prices(
        conn,
        table=_table(),
        as_of="2026-06-10",
        source="bundled",
        fetched_at="2026-06-12T00:00:00+00:00",
    )

    # A genuine mid-replace failure: the DELETE succeeds, then the INSERT raises
    # because the price value cannot be bound. The BEGIN IMMEDIATE transaction
    # must roll the DELETE back rather than leave the cache empty.
    with pytest.raises(sqlite3.ProgrammingError):
        save_cached_prices(
            conn,
            # type: ignore[dict-item] — deliberately wrong value type to fail the bind.
            table={"o4-mini": _UnbindablePrice()},  # type: ignore[dict-item]
            as_of="2026-07-01",
            source="https://prices.example/list.json",
            fetched_at="2026-07-01T00:00:00+00:00",
        )

    # The prior cache survives unchanged.
    loaded = load_cached_prices(conn)
    assert loaded is not None
    assert set(loaded.table) == {"gpt-5.5", "gpt-5.4-mini"}
    assert loaded.as_of == "2026-06-10"
