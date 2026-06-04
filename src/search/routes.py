"""HTTP route handlers for the search server (spec §7.1).

This module owns the seven ``/api/*`` route handlers, factored out of
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

Allowed deps: fastapi, search (appstate, deps, wire), store (reader, errors),
    appdb (recent_searches), common.config.
Forbidden: direct LLM/HTTP calls, imports from indexer/.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from appdb import recent_searches as recent_search_store
from search.appstate import AppState, get_app_state
from search.deps import get_app_db
from search.offload import LazySemaphore, run_blocking
from search.sessions import CurrentUser
from search.wire import (
    DocumentListResponse,
    FacetsResponse,
    MAX_PAGE_NUMBER,
    MAX_PAGE_SIZE,
    MAX_QUERY_LENGTH,
    SearchRequest,
    SearchResponse,
    StatsResponse,
    to_document_browse_query,
    to_document_list_response,
    to_facets_response,
    to_search_filters,
    to_search_response,
    to_stats_response,
)
from store import SchemaNotReadyError, StoreError

if TYPE_CHECKING:
    from common.config import Settings
    from search.core import SearchCore
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

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
        return IndexHealth(state="index-not-ready", reason=f"stats_error: {exc}")

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


def build_api_router(
    settings: Settings,
    resolve_core: Callable[[str], SearchCore],
    store_reader: StoreReader,
    *,
    require_reader: Callable[..., CurrentUser],
    require_member: Callable[..., CurrentUser],
    get_current_user: Callable[..., CurrentUser],
) -> APIRouter:
    """Build the ``/api`` router with all seven route handlers (spec §7.1).

    The handlers close over the injected dependencies; the app factory in
    ``search/api.py`` mounts the returned router.  ``/api/healthz`` is
    unauthenticated; search, facets, and stats need Read-only or above, and
    the reconcile trigger needs Member or above.

    Args:
        settings: Application settings.
        resolve_core: A callable that returns the live :class:`SearchCore` for
            the request's ``app.db`` path. Called per request so the search
            handler picks up a hot-loaded configuration change without a
            restart (web-redesign §5, Wave 4); in production this is
            :func:`search.api._resolve_search_core`. The callable owns its
            own caching — a steady-state request pays one cheap one-row
            ``SELECT``.
        store_reader: The read-side store, backing healthz, facets, and stats.
        require_reader: A FastAPI dependency requiring an authenticated
            caller of role Read-only or above; an API-key caller must also
            hold the ``api`` scope (web-redesign §5). Gates search, facets,
            and stats.
        require_member: A FastAPI dependency requiring role Member or above;
            an API-key caller must also hold the ``api`` scope. Gates the
            reconcile trigger.
        get_current_user: The FastAPI dependency resolving the request to a
            :class:`~search.sessions.CurrentUser`. The ``/api/search``
            handler uses it to attribute a recorded recent search.

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
    search_semaphore = LazySemaphore(settings.SEARCH_MAX_CONCURRENT)

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

        Offloaded: the body runs ``get_stats`` plus a ``PRAGMA quick_check``
        (a full-database integrity scan) under the StoreReader's lock, so it
        is dispatched to the threadpool to keep the Docker healthcheck off the
        event loop.
        """
        return await run_blocking(lambda: _healthz(settings, store_reader))

    @router.post("/api/search")
    async def search(
        body: SearchRequest,
        state: AppState = Depends(get_app_state),
        _role: object = Depends(require_reader),
        user: CurrentUser = Depends(get_current_user),
        app_db: sqlite3.Connection = Depends(get_app_db),
    ) -> SearchResponse:
        """Run the full agentic search pipeline and return a SearchResponse.

        Bounded by ``SEARCH_MAX_CONCURRENT`` to limit simultaneous LLM spend.
        The limit is resolved per request through *resolve_core* (which
        reads the live :class:`Settings`), so saving a new value via the
        Settings API takes effect immediately — no restart. A successful
        search by an authenticated caller is recorded in that caller's
        recent-search history. The :class:`SearchCore` is resolved per
        request so a saved configuration change takes effect on the next
        query — web-redesign §5, Wave 4.
        """
        # resolve_core opens app.db, runs ensure_schema, and on a config-version
        # change rebuilds the whole core (new StoreReader/index.db connection) —
        # all blocking SQLite, so it is offloaded off the event loop.
        core = await run_blocking(lambda: resolve_core(state.app_db_path))
        # core carries the Settings it was built from (see SearchCore.settings);
        # pick the SEARCH_MAX_CONCURRENT off that and apply it to the lazy
        # semaphore. set_limit is a no-op when nothing changed, and ignores
        # non-int values so a stub core in tests does not crash the handler.
        search_semaphore.set_limit(core.settings.SEARCH_MAX_CONCURRENT)
        result = await _search(body, core, search_semaphore)
        # The recent-search write is a blocking multi-statement SQLite
        # transaction (delete+insert+trim); keep it off the loop too.
        await run_blocking(lambda: _record_recent_search(app_db, user, body.query))
        return result

    @router.get("/api/facets", dependencies=[reader_auth])
    async def facets() -> FacetsResponse:
        """Return taxonomy facets for the search UI filter panel."""
        facet_set = await run_blocking(store_reader.list_facets)
        return to_facets_response(facet_set)

    @router.get("/api/stats", dependencies=[reader_auth])
    async def stats() -> StatsResponse:
        """Return summary statistics for the search index."""
        index_stats = await run_blocking(store_reader.get_stats)
        return to_stats_response(index_stats)

    @router.get("/api/documents", dependencies=[reader_auth])
    async def documents(  # noqa: PLR0913 — one param per browse filter
        page: int = Query(default=1, ge=1, le=MAX_PAGE_NUMBER),
        page_size: int = Query(default=24, ge=1, le=MAX_PAGE_SIZE),
        sort: Literal["created", "title", "added"] = Query(default="added"),
        descending: bool = Query(default=True),
        query: str | None = Query(default=None, max_length=MAX_QUERY_LENGTH),
        correspondent_id: int | None = Query(default=None),
        document_type_id: int | None = Query(default=None),
        tag_ids: list[int] = Query(default_factory=list, max_length=64),
        date_from: str | None = Query(default=None),
        date_to: str | None = Query(default=None),
    ) -> DocumentListResponse:
        """List indexed documents for the Library, paginated (web-redesign §5).

        Read-only role or above.  ``sort`` is one of ``created`` / ``title``
        / ``added`` (date indexed); ``query`` is an optional case-insensitive
        text match over title, correspondent and document type.  Returns a
        paginated envelope with the total match count for the UI pager.
        """
        return await _documents(
            settings,
            store_reader,
            page=page,
            page_size=page_size,
            sort=sort,
            descending=descending,
            text=query,
            correspondent_id=correspondent_id,
            document_type_id=document_type_id,
            tag_ids=tag_ids,
            date_from=date_from,
            date_to=date_to,
        )

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
    body: SearchRequest, core: SearchCore, semaphore: LazySemaphore
) -> SearchResponse:
    """Search handler body: bound concurrency, convert filters, run off the loop.

    The concurrency semaphore caps simultaneous LLM spend (§10.6); the actual
    ``core.answer`` is CPU-light wiring around blocking I/O (LLM HTTP + SQLite),
    so ``run_in_executor`` keeps the event loop unblocked while it runs.
    """
    ui_filters = to_search_filters(body.filters)

    async with semaphore.acquire():
        result = await run_blocking(
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


async def _documents(
    settings: Settings,
    store_reader: StoreReader,
    *,
    page: int,
    page_size: int,
    sort: str,
    descending: bool,
    text: str | None,
    correspondent_id: int | None,
    document_type_id: int | None,
    tag_ids: list[int],
    date_from: str | None,
    date_to: str | None,
) -> DocumentListResponse:
    """Library browse handler body: validate, query the store, convert.

    The query parameters are already bound and range-checked by FastAPI's
    ``Query`` constraints on the route.  This body maps them to the store
    browse shape, runs the (blocking) ``list_documents`` query off the event
    loop, and converts the page to the wire envelope.

    A ``sort`` value outside the allowed set is rejected by FastAPI before
    this body runs; the explicit :class:`ValueError` catch is defence in
    depth.  An index with no schema yet surfaces as a 503, consistent with
    the index-not-ready contract; any other store fault propagates as a 500.
    """
    try:
        browse_query = to_document_browse_query(
            page=page,
            page_size=page_size,
            sort=sort,
            descending=descending,
            text=text,
            date_from=date_from,
            date_to=date_to,
            correspondent_id=correspondent_id,
            document_type_id=document_type_id,
            tag_ids=tag_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        document_page = await run_blocking(
            lambda: store_reader.list_documents(browse_query)
        )
    except SchemaNotReadyError as exc:
        # The index has not been built yet — the same contract as healthz.
        log.info("api.documents_index_not_ready")
        raise HTTPException(
            status_code=503, detail="The search index is not ready"
        ) from exc

    return to_document_list_response(
        document_page,
        page_number=page,
        page_size=page_size,
        paperless_base_url=settings.PAPERLESS_URL.rstrip("/"),
    )


def _record_recent_search(
    app_db: sqlite3.Connection, user: CurrentUser, query: str
) -> None:
    """Record a successful search in the caller's recent-search history.

    Best-effort: a database error while writing the history row is logged
    and swallowed — it must never turn an otherwise-successful search into a
    failed request.

    Args:
        app_db: The per-request ``app.db`` connection.
        user: The authenticated user who ran the search.
        query: The verbatim search query to record.
    """
    try:
        recent_search_store.record(app_db, user_id=user.id, query=query)
    except Exception:
        # rationale: a recent-search write failure must not fail the search
        # itself (CODE_GUIDELINES §6.4). The search response has already been
        # built; logging and swallowing here is the correct outer-boundary act.
        log.warning("api.recent_search_record_failed", user_id=user.id)
