"""Tests for search.cache — the process-singleton TTL result cache (RAG-05).

The cache stores successful SearchResults keyed on
(normalised_query, filters, index_version). A clock is injected so TTL expiry
is deterministic — no time.sleep (CODE_GUIDELINES §11.7). No LLM is involved.
"""

from __future__ import annotations

from search.cache import (
    SearchResultCache,
    build_cache_key,
    get_search_result_cache,
    is_cacheable,
    reset_search_result_cache,
)
from store.reader import SearchFilters
from tests.helpers.factories import make_search_result, make_source_document


class _FakeClock:
    """A manually-advanced monotonic clock for deterministic TTL tests."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _key(
    query: str = "q",
    *,
    filters: SearchFilters | None = None,
    version: str = "1:1",
    asker: str | None = None,
):
    return build_cache_key(query=query, filters=filters, index_version=version, asker=asker)


def test_different_asker_makes_a_different_key() -> None:
    from search.cache import build_cache_key

    a = build_cache_key(query="my passport", filters=None, index_version="1:1", asker="Alice")
    b = build_cache_key(query="my passport", filters=None, index_version="1:1", asker="Bob")
    assert a != b


def test_same_asker_makes_the_same_key() -> None:
    from search.cache import build_cache_key

    a = build_cache_key(query="my passport", filters=None, index_version="1:1", asker="Alice")
    b = build_cache_key(query="my passport", filters=None, index_version="1:1", asker="Alice")
    assert a == b


def test_none_asker_defaults() -> None:
    from search.cache import build_cache_key

    key = build_cache_key(query="x", filters=None, index_version="1:1")
    assert key.asker is None


class TestPutAndGet:
    def test_put_then_get_returns_the_stored_result(self) -> None:
        cache = SearchResultCache(ttl_seconds=100, clock=_FakeClock())
        result = make_search_result(answer="cached answer")
        cache.put(_key(), result)
        assert cache.get(_key()) is result

    def test_miss_returns_none(self) -> None:
        cache = SearchResultCache(ttl_seconds=100, clock=_FakeClock())
        assert cache.get(_key("never stored")) is None

    def test_normalisation_collapses_whitespace_and_case(self) -> None:
        cache = SearchResultCache(ttl_seconds=100, clock=_FakeClock())
        result = make_search_result()
        cache.put(
            build_cache_key(
                query="Show My  Invoices", filters=None, index_version="1:1"
            ),
            result,
        )
        # Different spacing + case → same normalised key → hit.
        hit = cache.get(
            build_cache_key(query="show my invoices", filters=None, index_version="1:1")
        )
        assert hit is result


class TestTtl:
    def test_entry_expires_after_ttl(self) -> None:
        clock = _FakeClock()
        cache = SearchResultCache(ttl_seconds=100, clock=clock)
        cache.put(_key(), make_search_result())
        clock.advance(100)  # exactly at TTL → expired
        assert cache.get(_key()) is None

    def test_entry_lives_within_ttl(self) -> None:
        clock = _FakeClock()
        cache = SearchResultCache(ttl_seconds=100, clock=clock)
        cache.put(_key(), make_search_result())
        clock.advance(99)
        assert cache.get(_key()) is not None

    def test_zero_ttl_disables_the_cache(self) -> None:
        cache = SearchResultCache(ttl_seconds=0, clock=_FakeClock())
        cache.put(_key(), make_search_result())
        assert cache.get(_key()) is None


class TestIndexVersionInvalidation:
    def test_changing_index_version_misses(self) -> None:
        cache = SearchResultCache(ttl_seconds=100, clock=_FakeClock())
        cache.put(_key(version="3:10"), make_search_result())
        # A document indexed → counts change → version string changes → miss.
        assert cache.get(_key(version="4:13")) is None
        # The original version still hits (old entry not evicted, just unmatched).
        assert cache.get(_key(version="3:10")) is not None


class TestFiltersInKey:
    def test_different_filters_do_not_collide(self) -> None:
        cache = SearchResultCache(ttl_seconds=100, clock=_FakeClock())
        f1 = SearchFilters(
            date_from=None,
            date_to=None,
            correspondent_id=1,
            document_type_id=None,
            tag_ids=(),
        )
        f2 = SearchFilters(
            date_from=None,
            date_to=None,
            correspondent_id=2,
            document_type_id=None,
            tag_ids=(),
        )
        r1 = make_search_result(answer="for corr 1")
        cache.put(_key(filters=f1), r1)
        assert cache.get(_key(filters=f2)) is None
        assert cache.get(_key(filters=f1)) is r1


class TestBound:
    def test_eviction_keeps_the_cache_bounded(self) -> None:
        from search.cache import _MAX_ENTRIES

        cache = SearchResultCache(ttl_seconds=10000, clock=_FakeClock())
        for i in range(_MAX_ENTRIES + 50):
            cache.put(_key(f"query-{i}"), make_search_result())
        assert cache.size() <= _MAX_ENTRIES


class TestIsCacheable:
    """Only a successful answer (non-empty, sourced, not a degrade sentinel) caches."""

    def test_answer_with_sources_is_cacheable(self) -> None:
        result = make_search_result(
            answer="A real answer [1].", sources=(make_source_document(),)
        )
        assert is_cacheable(result) is True

    def test_empty_answer_is_not_cacheable(self) -> None:
        result = make_search_result(answer="", sources=(make_source_document(),))
        assert is_cacheable(result) is False

    def test_no_sources_is_not_cacheable(self) -> None:
        result = make_search_result(answer="text", sources=())
        assert is_cacheable(result) is False

    def test_no_match_sentinel_is_not_cacheable(self) -> None:
        from search.core import _NO_MATCHES_ANSWER

        result = make_search_result(
            answer=_NO_MATCHES_ANSWER, sources=(make_source_document(),)
        )
        assert is_cacheable(result) is False

    def test_synth_final_fallback_sentinel_is_not_cacheable(self) -> None:
        from search.synthesizer import _FALLBACK_FINAL_ANSWER

        result = make_search_result(
            answer=_FALLBACK_FINAL_ANSWER, sources=(make_source_document(),)
        )
        assert is_cacheable(result) is False


class TestSingletonAccessor:
    def test_accessor_returns_the_same_instance(self) -> None:
        reset_search_result_cache()
        first = get_search_result_cache(100)
        second = get_search_result_cache(100)
        assert first is second

    def test_reset_clears_the_singleton(self) -> None:
        first = get_search_result_cache(100)
        reset_search_result_cache()
        second = get_search_result_cache(100)
        assert first is not second
