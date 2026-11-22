"""Tests for the keyword match expression bounds and the cached health check."""

from __future__ import annotations

from store.reader import _lookups
from store.reader._filters import MAX_FTS_TERMS, build_match_expr
from store.reader._reader import StoreReader
from tests.helpers.factories import make_search_filters
from tests.helpers.store import make_store_settings, open_reader


def test_match_expr_without_repeats_is_and_of_quoted_terms() -> None:
    assert build_match_expr(["boiler", 'wa"rranty']) == '"boiler" AND "wa""rranty"'


def test_match_expr_drops_repeated_terms_keeping_first_seen_order() -> None:
    assert build_match_expr(["b", "a", "b", "a", "c"]) == '"b" AND "a" AND "c"'


def test_match_expr_keeps_at_most_the_term_cap() -> None:
    terms = [f"t{i}" for i in range(MAX_FTS_TERMS + 10)]

    expr = build_match_expr(terms)

    assert expr.count(" AND ") == MAX_FTS_TERMS - 1
    assert expr.startswith('"t0" AND "t1"')
    assert f'"t{MAX_FTS_TERMS}"' not in expr


def test_keyword_search_with_a_term_repeated_returns_same_hits(
    populated_db: str,
) -> None:
    reader = open_reader(populated_db)
    once = reader.keyword_search(["boiler"], 10, make_search_filters())
    many = reader.keyword_search(["boiler"] * 300, 10, make_search_filters())
    reader.close()

    assert once and many == once


def _reader_with_clock(db_path: str, clock) -> StoreReader:
    return StoreReader(make_store_settings(db_path), clock=clock)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_quick_check_is_cached_for_thirty_seconds(
    populated_db: str, monkeypatch
) -> None:
    calls: list[int] = []
    real = _lookups.quick_check

    def counting(conn, lock):
        calls.append(1)
        return real(conn, lock)

    monkeypatch.setattr(_lookups, "quick_check", counting)
    clock = _Clock()
    reader = _reader_with_clock(populated_db, clock)

    assert reader.quick_check() is True
    clock.now += 29
    assert reader.quick_check() is True
    assert len(calls) == 1

    clock.now += 2
    assert reader.quick_check() is True
    assert len(calls) == 2
    reader.close()


def test_quick_check_caches_a_failing_result(populated_db: str, monkeypatch) -> None:
    calls: list[int] = []

    def failing(conn, lock):
        calls.append(1)
        return False

    monkeypatch.setattr(_lookups, "quick_check", failing)
    reader = _reader_with_clock(populated_db, _Clock())

    assert reader.quick_check() is False
    assert reader.quick_check() is False
    assert len(calls) == 1
    reader.close()
