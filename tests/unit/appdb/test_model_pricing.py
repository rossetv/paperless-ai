"""Tests for appdb.model_pricing, the cached model-price book."""

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
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def _table() -> dict[str, CachedModelPrice]:
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

    # A disjoint second table must replace the first, not merge with it.
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
    """A price sqlite cannot bind, so the INSERT fails after the DELETE has run."""

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

    # The transaction must roll the DELETE back rather than leave the cache empty.
    with pytest.raises(sqlite3.ProgrammingError):
        save_cached_prices(
            conn,
            # Deliberately the wrong value type, so the bind fails.
            table={"o4-mini": _UnbindablePrice()},  # type: ignore[dict-item]
            as_of="2026-07-01",
            source="https://prices.example/list.json",
            fetched_at="2026-07-01T00:00:00+00:00",
        )

    loaded = load_cached_prices(conn)
    assert loaded is not None
    assert set(loaded.table) == {"gpt-5.5", "gpt-5.4-mini"}
    assert loaded.as_of == "2026-06-10"
