"""Process-wide TTL cache of search results.

A search costs a query embedding plus 2–3 LLM calls, so an identical repeat (a
back-navigation, a re-ask) over an unchanged index reuses the prior result. The
HTTP and MCP search paths share this one cache.

The key carries an index version, ``document_count:chunk_count:latest_indexed_at``.
The counts move when documents are indexed or pruned; ``MAX(indexed_at)`` moves
on an in-place re-index that keeps the chunk count. ``last_reconcile_at`` is not
used because it changes every cycle, even a no-op one, and would drop the whole
cache. A same-cycle add-and-prune that leaves all three unchanged goes unseen
until the TTL expires; that is accepted rather than paying for a content digest.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

import structlog

from search.models import SearchResult
from store.reader import SearchFilters

log = structlog.get_logger(__name__)

# A memory-leak guard, not a tuning knob; the TTL is the real lifetime.
_MAX_ENTRIES = 512


@dataclass(frozen=True, slots=True)
class _CacheKey:
    """The identity of a cached answer.

    *asker* is part of the key so a personalised answer for one user is never
    served to another; callers without an asker share one namespace.
    """

    normalised_query: str
    filters: SearchFilters | None
    index_version: str
    asker: str | None = None


def build_cache_key(
    *,
    query: str,
    filters: SearchFilters | None,
    index_version: str,
    asker: str | None = None,
) -> _CacheKey:
    """Build a :class:`_CacheKey`, collapsing whitespace and folding case."""
    normalised_query = " ".join(query.split()).casefold()
    return _CacheKey(
        normalised_query=normalised_query,
        filters=filters,
        index_version=index_version,
        asker=asker,
    )


def is_cacheable(result: SearchResult) -> bool:
    """Return whether *result* should be written to the cache.

    An answered result needs a real answer and a source; the synthesiser's
    fallback answer is never cached, so a model recovery shows on the next
    query. Clarify and no-match results are cached too: a no-match is dropped
    when indexing moves the index version.
    """
    # Local import: synthesizer imports this module.
    from search.synthesizer import _FALLBACK_FINAL_ANSWER

    if result.answer == _FALLBACK_FINAL_ANSWER:
        return False
    if result.outcome_kind in ("no_match", "clarify"):
        return True
    return bool(result.answer) and bool(result.sources)


class SearchResultCache:
    """A bounded, TTL'd, thread-safe map of cache key -> SearchResult.

    ``ttl_seconds=0`` disables the cache (``SEARCH_CACHE_TTL_SECONDS=0``).
    *clock* is injectable for tests.
    """

    def __init__(
        self, ttl_seconds: int, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        # OrderedDict gives O(1) oldest-first eviction.
        self._entries: OrderedDict[_CacheKey, tuple[SearchResult, float]] = (
            OrderedDict()
        )

    def get(self, key: _CacheKey) -> SearchResult | None:
        """Return the cached result for *key*, or None on miss/expiry/disabled."""
        if self._ttl_seconds == 0:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            result, stored_at = entry
            if self._clock() - stored_at >= self._ttl_seconds:
                del self._entries[key]
                return None
            return result

    def put(self, key: _CacheKey, result: SearchResult) -> None:
        """Store *result* under *key*, evicting the oldest entry when full."""
        if self._ttl_seconds == 0:
            return
        with self._lock:
            self._entries[key] = (result, self._clock())
            self._entries.move_to_end(key)
            while len(self._entries) > _MAX_ENTRIES:
                self._entries.popitem(last=False)

    def size(self) -> int:
        """Return the number of currently-held entries (for tests/observability)."""
        with self._lock:
            return len(self._entries)

    def reset(self) -> None:
        """Drop every entry — for tests, never the request path."""
        with self._lock:
            self._entries.clear()


_search_result_cache: SearchResultCache | None = None
_search_result_cache_lock = threading.Lock()


def get_search_result_cache(ttl_seconds: int) -> SearchResultCache:
    """Return the process-wide :class:`SearchResultCache`, building it once.

    *ttl_seconds* is used only when building; a changed TTL applies after
    :func:`reset_search_result_cache`, which every settings save calls.
    """
    global _search_result_cache
    if _search_result_cache is not None:
        return _search_result_cache
    with _search_result_cache_lock:
        if _search_result_cache is None:
            _search_result_cache = SearchResultCache(ttl_seconds)
        return _search_result_cache


def reset_search_result_cache() -> None:
    """Drop the cache singleton; the next get rebuilds it.

    Called on a settings change so answers made under the old model, prompt or
    TTL are not served on.
    """
    global _search_result_cache
    with _search_result_cache_lock:
        _search_result_cache = None
