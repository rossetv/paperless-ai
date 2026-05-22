"""HTTP route handlers for the search server (spec §7.1).

This module owns the six ``/api/*`` route handlers, factored out of
``search/api.py`` so the app factory there is component wiring only
(``CODE_GUIDELINES.md`` §3.1).  :func:`build_api_router` returns a configured
:class:`~fastapi.APIRouter` the app factory mounts; the handlers close over the
injected ``settings``, ``core``, and ``store_reader``.

The healthz three-state decision is :func:`evaluate_index_health` — a pure,
synchronous, testable helper that takes a :class:`~store.reader.StoreReader`
and returns an :class:`IndexHealth`.  It performs no ``sqlite3`` inspection:
the store raises :class:`~store.SchemaNotReadyError` for a present-but-empty
database, so this module distinguishes "not built yet" from "corrupt" through
a typed exception, never a string match (``CODE_GUIDELINES.md`` §8.2).

Allowed deps: fastapi, search (auth, wire), store (reader, errors),
    common.config.
Forbidden: sqlite3, direct LLM/HTTP calls, imports from indexer/.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeVar

import structlog
from fastapi import APIRouter, Depends, Response

from search.wire import (
    FacetsResponse,
    SearchRequest,
    SearchResponse,
    StatsResponse,
    to_facets_response,
    to_search_filters,
    to_search_response,
    to_stats_response,
)
from store import SchemaNotReadyError, StoreError

if TYPE_CHECKING:
    from collections.abc import Callable

    from common.config import Settings
    from search.core import SearchCore
    from search.sessions import CurrentUser
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

# Return type of a blocking call dispatched through _run_blocking.
_T = TypeVar("_T")

# The reconciliation sentinel file name (spec §5.8).  Written alongside the
# index DB; picked up by the indexer's polling loop.
_RECONCILE_SENTINEL_NAME = "reconcile.request"

# HTTP status the healthz endpoint returns when the index is not yet usable.
_HEALTHZ_UNAVAILABLE_STATUS = 503

#: The three index-health states healthz can report (spec §4.7).
IndexHealthState = Literal["ok", "index-not-ready", "index-corrupt"]


@dataclass(frozen=True, slots=True)
class IndexHealth:
    """The outcome of an index-health evaluation (spec §4.7).

    Attributes:
        state: ``"ok"`` when the index is built, reconciled, and passes the
            integrity check; ``"index-not-ready"`` when the indexer has not
            finished building it; ``"index-corrupt"`` when integrity fails.
        reason: A short machine-readable reason for a non-ok state, for the
            structured log; an empty string when the state is ``"ok"``.
    """

    state: IndexHealthState
    reason: str


# A reusable "index is ready" outcome — the only ok IndexHealth value.
_INDEX_HEALTHY = IndexHealth(state="ok", reason="")


def evaluate_index_health(store_reader: StoreReader) -> IndexHealth:
    """Evaluate the three-state health of the index (spec §4.7).

    The decision, factored out of the healthz handler so it is unit-testable
    in isolation:

    - **ok** — ``get_stats`` succeeds (the schema exists), the index has been
      reconciled at least once (``last_reconcile_at`` is set), and
      ``quick_check`` reports no corruption.
    - **index-not-ready** — the schema is absent (a present-but-empty database
      the indexer has not initialised — surfaced as
      :class:`~store.SchemaNotReadyError`), OR the schema exists but no
      reconciliation has completed, OR ``get_stats`` failed unexpectedly.
    - **index-corrupt** — the schema and a reconcile timestamp are present but
      ``quick_check`` reports corruption.

    The caller is expected to have already confirmed the database *file*
    exists; an absent file is the caller's own ``index-not-ready`` case.

    Args:
        store_reader: The read-side store interface for the index.

    Returns:
        The :class:`IndexHealth` describing the index's state.
    """
    try:
        stats = store_reader.get_stats()
    except SchemaNotReadyError:
        # A present-but-empty database — the indexer has not built the schema.
        return IndexHealth(state="index-not-ready", reason="schema_missing")
    except StoreError as exc:
        return IndexHealth(
            state="index-not-ready", reason=f"stats_error: {exc}"
        )

    if stats.last_reconcile_at is None:
        # Schema present, but the first reconciliation has not finished.
        return IndexHealth(state="index-not-ready", reason="never_reconciled")

    try:
        integrity_ok = store_reader.quick_check()
    except StoreError:
        integrity_ok = False

    if not integrity_ok:
        return IndexHealth(state="index-corrupt", reason="quick_check_failed")

    return _INDEX_HEALTHY


def _health_response(state: IndexHealthState) -> Response:
    """Build the healthz JSON response for *state*.

    A 200 for the ``"ok"`` state; a 503 for ``"index-not-ready"`` and
    ``"index-corrupt"`` so the Docker healthcheck marks the container unhealthy
    while the index is unusable.
    """
    status_code = 200 if state == "ok" else _HEALTHZ_UNAVAILABLE_STATUS
    return Response(
        content=f'{{"status":"{state}"}}',
        status_code=status_code,
        media_type="application/json",
    )


async def _run_blocking(call: Callable[[], _T]) -> _T:
    """Run a blocking store/LLM call on the event loop's default executor.

    The store and the LLM client perform blocking I/O; running them directly
    in an async handler would stall the event loop.  ``run_in_executor`` keeps
    the loop free to serve other requests.  The return type is preserved so
    callers need no cast.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, call)


class _LazySemaphore:
    """An :class:`asyncio.Semaphore` created on first use, not at build time.

    A semaphore must be bound to the event loop that awaits it.  The router is
    built before the serving loop exists, so the semaphore is created lazily on
    the first :meth:`acquire`.  asyncio's single-threaded contract means only
    one coroutine touches ``_semaphore`` at a time — no lock is needed.

    Args:
        max_concurrent: The simultaneous-holder ceiling.
    """

    def __init__(self, max_concurrent: int) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore: asyncio.Semaphore | None = None

    def acquire(self) -> asyncio.Semaphore:
        """Return the semaphore, creating it on first use.

        The returned object is an async context manager — ``async with
        lazy.acquire():`` holds one permit for the duration of the block.
        """
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore


def build_api_router(
    settings: Settings,
    core: SearchCore,
    store_reader: StoreReader,
    *,
    require_reader: Callable[..., CurrentUser],
    require_member: Callable[..., CurrentUser],
) -> APIRouter:
    """Build the ``/api`` router with all six route handlers (spec §7.1).

    The handlers close over the injected dependencies; the app factory in
    ``search/api.py`` mounts the returned router.  ``/api/healthz`` is
    unauthenticated; search, facets, and stats need Read-only or above, and
    the reconcile trigger needs Member or above.

    Args:
        settings: Application settings.
        core: The search pipeline entry point, backing ``/api/search``.
        store_reader: The read-side store, backing healthz, facets, and stats.
        require_reader: A FastAPI dependency requiring an authenticated user
            of role Read-only or above. Gates search, facets, and stats.
        require_member: A FastAPI dependency requiring role Member or above.
            Gates the reconcile trigger.

    Returns:
        A configured :class:`~fastapi.APIRouter`.
    """
    router = APIRouter()
    reader_auth = Depends(require_reader)
    member_auth = Depends(require_member)

    # The /api/search concurrency cap (spec §7.4, CODE_GUIDELINES §10.6).  The
    # semaphore is created lazily on the first search so it is always bound to
    # the event loop actually serving requests, not whichever loop (if any) was
    # running at router-build time.  asyncio's single-threaded contract means
    # only one coroutine touches the holder at a time, so no lock is needed.
    search_semaphore = _LazySemaphore(settings.SEARCH_MAX_CONCURRENT)

    # response_model=None: healthz returns a hand-built Response (a fixed
    # JSON body and an explicit status code), so FastAPI must not try to
    # derive a response model from the return annotation.
    @router.get("/api/healthz", response_model=None)
    async def healthz() -> Response:
        """Liveness check; surfaces index state to the Docker healthcheck.

        Three outcomes (spec §4.7): 200 ``{"status": "ok"}`` when the index is
        built, reconciled, and healthy; 503 ``{"status": "index-not-ready"}``
        when the database is absent or the indexer has not finished; 503
        ``{"status": "index-corrupt"}`` when integrity fails.  The handler
        never raises — any unexpected error becomes a clean 503.
        """
        return _healthz(settings, store_reader)

    @router.post("/api/search", dependencies=[reader_auth])
    async def search(body: SearchRequest) -> SearchResponse:
        """Run the full agentic search pipeline and return a SearchResponse.

        Bounded by ``SEARCH_MAX_CONCURRENT`` to limit simultaneous LLM spend.
        """
        return await _search(body, core, search_semaphore)

    @router.get("/api/facets", dependencies=[reader_auth])
    async def facets() -> FacetsResponse:
        """Return taxonomy facets for the search UI filter panel."""
        facet_set = await _run_blocking(store_reader.list_facets)
        return to_facets_response(facet_set)

    @router.get("/api/stats", dependencies=[reader_auth])
    async def stats() -> StatsResponse:
        """Return summary statistics for the search index."""
        index_stats = await _run_blocking(store_reader.get_stats)
        return to_stats_response(index_stats)

    @router.post("/api/reconcile", dependencies=[member_auth])
    async def reconcile() -> Response:
        """Touch the reconciliation sentinel file and return 202 Accepted.

        The indexer's polling loop detects the sentinel on its next slice and
        starts an immediate reconciliation cycle (spec §5.8).

        Security: writes ONLY the sentinel — never the index DB.
        """
        return _reconcile(settings)

    return router


# ---------------------------------------------------------------------------
# Handler bodies — pure of FastAPI routing, easy to read and test
# ---------------------------------------------------------------------------


def _healthz(settings: Settings, store_reader: StoreReader) -> Response:
    """Liveness handler body: file check, then the three-state evaluation."""
    db_path = Path(settings.INDEX_DB_PATH)
    if not db_path.exists():
        # The indexer has not created the DB yet (spec §3.2).
        log.info("api.healthz_not_ready", reason="db_absent")
        return _health_response("index-not-ready")

    health = evaluate_index_health(store_reader)
    if health.state == "ok":
        return _health_response("ok")

    if health.state == "index-corrupt":
        log.warning("api.healthz_corrupt", reason=health.reason)
    else:
        log.info("api.healthz_not_ready", reason=health.reason)
    return _health_response(health.state)


async def _search(
    body: SearchRequest, core: SearchCore, semaphore: _LazySemaphore
) -> SearchResponse:
    """Search handler body: bound concurrency, convert filters, run off the loop.

    The concurrency semaphore caps simultaneous LLM spend (§10.6); the actual
    ``core.answer`` is CPU-light wiring around blocking I/O (LLM HTTP + SQLite),
    so ``run_in_executor`` keeps the event loop unblocked while it runs.
    """
    ui_filters = to_search_filters(body.filters)

    async with semaphore.acquire():
        result = await _run_blocking(
            lambda: core.answer(query=body.query, ui_filters=ui_filters)
        )
    return to_search_response(result)


def _reconcile(settings: Settings) -> Response:
    """Reconcile handler body: touch the sentinel, return 202 Accepted."""
    db_dir = Path(settings.INDEX_DB_PATH).parent
    sentinel = db_dir / _RECONCILE_SENTINEL_NAME
    sentinel.touch()
    log.info("api.reconcile_triggered", sentinel=str(sentinel))
    return Response(status_code=202)
