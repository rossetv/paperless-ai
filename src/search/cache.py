"""Process-singleton TTL cache of search results (RAG-05).

Answered, clarify, and no-match results are all cached, so an identical repeat
(a back-navigation, a re-ask) is served without re-running the pipeline; the
synthesiser final-mode fallback is a degrade sentinel and is never cached. A
no-match is invalidated not by a separate timer but by the index-version
component of the cache key — a reconciliation that indexes or prunes a document
moves the version and drops every prior no-match, so a newly-indexed document is
searchable on the next query (see :func:`is_cacheable`).

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
The cache key carries an *index version* —
``f"{document_count}:{chunk_count}:{latest_indexed_at}"`` from
``StoreReader.get_stats`` (computed by the caller in ``search.core``, not here).
The first two components move when a document is indexed, re-chunked, or pruned.
The third, ``MAX(documents.indexed_at)``, is the *content* signal: the indexer
stamps ``indexed_at`` on every upsert, so an **in-place** re-index — a corrected
OCR, a re-classification, an edited title/tags — that happens to chunk to the
same number of chunks (so both counts are unchanged) still advances the version
and evicts the stale answer on the next query. Before this signal existed, such
an in-place change went unseen and a stale answer was served until the TTL
expired (``SEARCH_CACHE_TTL_SECONDS``, default 4 h).

``indexed_at`` is deliberately chosen over ``last_reconcile_at``: the latter is
rewritten at the end of every reconcile cycle, including no-op ones, so keying on
it would drop the whole cache each cycle and evict a valid no-match after a
reconcile that indexed nothing — the staleness the count pair already handled
correctly. The remaining un-detected case is a single same-cycle add-and-prune
that leaves the counts *and* ``MAX(indexed_at)`` unchanged (the pruned document
held the newest timestamp); that residual staleness is bounded by the TTL, which
is why a full content digest is still not warranted at this scale (§14.6).

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
            (``document_count:chunk_count:latest_indexed_at``); a change —
            including an in-place re-index that moves only the content signal —
            invalidates prior keys.
        asker: The sanitised asker identity, or None. Included so a personalised
            answer for one user is never served to another (cross-user-leak
            guard). Two users sending the identical query key to different entries
            when an asker is set; None callers share one namespace.
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
    """Build a :class:`_CacheKey`, normalising the query.

    The query is whitespace-collapsed and case-folded so "Show My  Invoices"
    and "show my invoices" share one entry. The *asker* is included verbatim so
    a personalised answer for one user is never served to another — two users
    sending the identical query map to different entries when an asker is set.

    Args:
        query: The raw user query.
        filters: The authoritative UI filters, or None.
        index_version: The ``document_count:chunk_count:latest_indexed_at``
            signal.
        asker: The sanitised asker identity, or None for an anonymous query.

    Returns:
        The cache key.
    """
    normalised_query = " ".join(query.split()).casefold()
    return _CacheKey(
        normalised_query=normalised_query,
        filters=filters,
        index_version=index_version,
        asker=asker,
    )


def is_cacheable(result: SearchResult) -> bool:
    """Return whether *result* should be written to the cache (RAG-05).

    Answered, clarify, and no-match results are all cached so an identical repeat
    (a back-navigation, a re-ask) is served without re-running the pipeline:

    * **answered** — cached only when it carries a real answer and at least one
      source. The synthesiser final-mode fallback rides on an ``answered``
      outcome but is a degrade sentinel — never cached, so a model recovery is
      visible on the very next query.
    * **clarify** — cached. Re-asking the identical vague query cannot become
      answerable; a user who reworks the wording keys to a different entry
      anyway, so caching is safe and saves the planner call on an exact repeat.
    * **no_match** — cached, and invalidated by the cache key's index version
      rather than a timer: a reconciliation that indexes a document moves the
      index version (a count or the ``latest_indexed_at`` content signal) and
      drops every prior no-match, so a newly-indexed document is searchable on
      the next query. A no-match over an unchanged corpus stays a no-match, so
      serving it from cache is correct.

    The sentinel is imported lazily to avoid a circular import: ``synthesizer``
    imports this module, so importing it at module scope would cycle.
    """
    # rationale: function-local import breaks the cache <-> synthesizer import
    # cycle; the constant is read only on this rare write path.
    from search.synthesizer import _FALLBACK_FINAL_ANSWER

    if result.answer == _FALLBACK_FINAL_ANSWER:
        return False
    if result.outcome_kind in ("no_match", "clarify"):
        return True
    # answered: only a real, sourced answer is worth a cache entry.
    return bool(result.answer) and bool(result.sources)


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
# §8.5). The first caller fixes the TTL; subsequent calls reuse the existing
# instance and ignore their ttl_seconds argument. A changed
# SEARCH_CACHE_TTL_SECONDS therefore takes effect only after
# reset_search_result_cache() drops the singleton — which the Settings save path
# does on every config change (api.py) — so the next get rebuilds at the new
# TTL. The TTL is not pinned for the process lifetime; it hot-reloads on a
# config change, like the rest of Wave 4's settings.
_search_result_cache: SearchResultCache | None = None
_search_result_cache_lock = threading.Lock()


def get_search_result_cache(ttl_seconds: int) -> SearchResultCache:
    """Return the process-wide :class:`SearchResultCache`, building it once.

    Args:
        ttl_seconds: The TTL the singleton is built with on first call; ignored
            while a singleton already exists. A changed TTL takes effect after
            :func:`reset_search_result_cache` drops the singleton (the Settings
            save path calls it on every config change), so the next call here
            rebuilds the cache at the new TTL.

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
    """Drop the process-wide cache singleton.

    Called on a configuration change (so an edited answer model / reasoning
    effort / top-k / prompt is not served a pre-change answer for up to the
    TTL, and a new ``SEARCH_CACHE_TTL_SECONDS`` takes effect), and by tests for
    isolation. The next :func:`get_search_result_cache` rebuilds it lazily.
    """
    global _search_result_cache
    with _search_result_cache_lock:
        _search_result_cache = None
