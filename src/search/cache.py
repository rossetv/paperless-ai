"""Process-singleton TTL cache of successful search answers (RAG-05).

Why a process-global singleton
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A search re-pays a query embedding plus 2–3 LLM calls every time. A
request-scoped cache would never hit; the saving only exists if a byte-identical
repeat query, over an unchanged index, reuses a prior answer. The search server
is one process serving the HTTP ``/api/search`` and the MCP ``ask_documents``
paths (both funnel through ``SearchCore.answer``), and ``search/api.py`` already
keeps the core/planner/synth as process singletons — so a process-wide result
cache is the right scope and is shared by both paths.

This is exactly the *documented singleton owning a* ``threading.Lock`` that
CODE_GUIDELINES §8.5 permits, mirroring ``common.concurrency.llm_limiter``. The
cache declares **both** a TTL and a max-size bound (§14.5).

Invalidation
~~~~~~~~~~~~
The cache key carries an *index version* — ``f"{document_count}:{chunk_count}"``
from ``StoreReader.get_stats`` (computed by the caller, not here). When a
document is indexed, re-chunked, or pruned, the counts move, the version string
changes, and every prior entry stops matching — newly-indexed documents are
never invisible beyond the moment the index changes (spec §7).

Allowed deps: search.models (SearchResult), store.reader (SearchFilters),
    standard library.
Forbidden: no FastAPI, no MCP, no sqlite3, no LLM/HTTP calls.
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

# Hard upper bound on cached entries — a memory-leak guard, never a tuning knob.
# A homelab query volume never approaches this; the TTL is the real lifetime.
_MAX_ENTRIES = 512


@dataclass(frozen=True, slots=True)
class _CacheKey:
    """The identity of a cached answer.

    Frozen + slots so it is hashable and usable as a dict key.

    Attributes:
        normalised_query: The query with whitespace collapsed and case folded.
        filters: The authoritative UI filters, or None for an unfiltered query.
        index_version: A cheap stable signal of the indexed corpus state
            (``document_count:chunk_count``); a change invalidates prior keys.
    """

    normalised_query: str
    filters: SearchFilters | None
    index_version: str


def build_cache_key(
    *, query: str, filters: SearchFilters | None, index_version: str
) -> _CacheKey:
    """Build a :class:`_CacheKey`, normalising the query.

    The query is whitespace-collapsed and case-folded so "Show My  Invoices"
    and "show my invoices" share one entry.

    Args:
        query: The raw user query.
        filters: The authoritative UI filters, or None.
        index_version: The ``document_count:chunk_count`` signal.

    Returns:
        The cache key.
    """
    normalised_query = " ".join(query.split()).casefold()
    return _CacheKey(
        normalised_query=normalised_query,
        filters=filters,
        index_version=index_version,
    )


def is_cacheable(result: SearchResult) -> bool:
    """Return whether *result* is a successful answer worth caching (RAG-05).

    Cache successful answers only: a non-empty answer with at least one source,
    excluding the two degrade sentinels (the no-match answer and the synthesiser
    final-mode fallback). A no-match result is cheap to recompute (no synth
    call), and excluding failures means a fix — a re-index, a model recovery —
    is visible on the very next query (spec §4.5).

    The two sentinels are imported lazily to avoid a circular import: ``core``
    and ``synthesizer`` both import this module, so importing them at module
    scope would cycle.
    """
    if not result.answer or not result.sources:
        return False
    # rationale: function-local import breaks the cache <-> core/synthesizer
    # import cycle; these constants are read only on this rare write path.
    from search.core import _NO_MATCHES_ANSWER
    from search.synthesizer import _FALLBACK_FINAL_ANSWER

    return result.answer not in (_NO_MATCHES_ANSWER, _FALLBACK_FINAL_ANSWER)


class SearchResultCache:
    """A bounded, TTL'd, thread-safe map of cache key -> SearchResult.

    A ``ttl_seconds`` of ``0`` disables the cache (every ``get`` misses, every
    ``put`` is a no-op) — the kill-switch behind ``SEARCH_CACHE_TTL_SECONDS=0``.

    Args:
        ttl_seconds: Entry lifetime; ``0`` disables the cache.
        clock: A monotonic time source, injected for deterministic tests
            (CODE_GUIDELINES §11.7). Defaults to :func:`time.monotonic`.
    """

    def __init__(
        self, ttl_seconds: int, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        # OrderedDict gives O(1) oldest-first eviction via move_to_end/popitem.
        self._entries: OrderedDict[_CacheKey, tuple[SearchResult, float]] = (
            OrderedDict()
        )

    def get(self, key: _CacheKey) -> SearchResult | None:
        """Return the cached result for *key*, or None on miss/expiry/disabled.

        An expired entry is deleted on access. When the cache is disabled
        (TTL 0) every call is a miss.
        """
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
        """Store *result* under *key*. A no-op when the cache is disabled.

        Evicts the oldest-stored entry first when at capacity, so the cache
        stays bounded by :data:`_MAX_ENTRIES` (CODE_GUIDELINES §14.5).
        """
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


# The documented process-wide singleton and its accessor (CODE_GUIDELINES §4.6,
# §8.5). The first caller fixes the TTL ceiling for the process lifetime; a
# hot-reloaded SEARCH_CACHE_TTL_SECONDS takes effect on the next process (it is
# an operational ceiling, not per-request state — spec §4.4).
_search_result_cache: SearchResultCache | None = None
_search_result_cache_lock = threading.Lock()


def get_search_result_cache(ttl_seconds: int) -> SearchResultCache:
    """Return the process-wide :class:`SearchResultCache`, building it once.

    Args:
        ttl_seconds: The TTL the singleton is built with on first call;
            ignored on subsequent calls (the ceiling is process-fixed).

    Returns:
        The shared cache instance.
    """
    global _search_result_cache
    if _search_result_cache is not None:
        return _search_result_cache
    with _search_result_cache_lock:
        if _search_result_cache is None:
            _search_result_cache = SearchResultCache(ttl_seconds)
        return _search_result_cache


def reset_search_result_cache() -> None:
    """Drop the process-wide cache singleton — for tests only."""
    global _search_result_cache
    with _search_result_cache_lock:
        _search_result_cache = None
