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

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from appdb import recent_searches as recent_search_store
from appdb.connection import connect
from search.appstate import AppState, get_app_state
from search.deps import Caller, get_app_db, resolve_caller
from search.errors import LlmBudgetExceededError
from search.identity import resolve_asker
from search.offload import LazySemaphore, run_blocking
from search.sessions import CurrentUser
from search.spend_quota import (
    QuotaExceededError,
    check_quota,
    record_usage,
    record_usage_blocking,
)
from search.wire import (
    BrowseSort,
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
from search.wire.stream import error_line, event_line, result_line
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

# HTTP status returned when an API key has reached its daily LLM-token quota.
_QUOTA_EXCEEDED_STATUS = 429

# Heartbeat cadence for the search stream. A phase such as synthesis can hold the
# worker on a single LLM call for 40s+ with nothing to enqueue; without traffic an
# idle proxy or tunnel (e.g. Cloudflare) closes the connection and the SPA reports
# a bare "network error". Emitting a blank NDJSON line on this interval keeps the
# socket warm — the client skips blank lines, so no frame is fabricated.
_STREAM_KEEPALIVE_SECONDS = 15.0

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


def _seconds_to_next_utc_midnight(now: datetime) -> int:
    """Return whole seconds from *now* until the next UTC midnight.

    The quota bucket is keyed on the UTC calendar date, so it refills the moment
    a new UTC day begins. This is the ``Retry-After`` a quota-rejected client is
    told to wait — at least 1 so a request landing in the final second of the
    day is never told to retry immediately.
    """
    tomorrow = (now + timedelta(days=1)).date()
    next_midnight = datetime(
        tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc
    )
    return max(1, int((next_midnight - now).total_seconds()))


def _raise_quota_429(exc: QuotaExceededError) -> None:
    """Translate a :class:`QuotaExceededError` into an HTTP 429 with Retry-After.

    The ``Retry-After`` header points at the next UTC midnight, when the daily
    bucket refills; the JSON detail names the cap so a client can react without
    parsing the message. The chain is severed with ``from exc`` so the traceback
    is preserved for the server log (the detail carries no secret).
    """
    retry_after = _seconds_to_next_utc_midnight(datetime.now(timezone.utc))
    raise HTTPException(
        status_code=_QUOTA_EXCEEDED_STATUS,
        detail=(
            "Daily LLM token quota for this API key has been reached. "
            "It resets at UTC midnight."
        ),
        headers={"Retry-After": str(retry_after)},
    ) from exc


def build_api_router(
    settings: Settings,
    resolve_core: Callable[[str], SearchCore],
    store_reader: StoreReader,
    *,
    require_reader: Callable[..., CurrentUser],
    require_member: Callable[..., CurrentUser],
    get_current_user: Callable[..., CurrentUser],
    search_semaphore: LazySemaphore,
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
        search_semaphore: The ``/api/search`` concurrency cap (spec §7.4,
            CODE_GUIDELINES §10.6), shared with the MCP tool surface so
            ``SEARCH_MAX_CONCURRENT`` is one ceiling across both, not 2N. It is
            created by the app factory and binds lazily to the serving event
            loop on first acquire; asyncio's single-threaded contract means only
            one coroutine touches it at a time, so no lock is needed.

    Returns:
        A configured :class:`~fastapi.APIRouter`.
    """
    router = APIRouter()
    reader_auth = Depends(require_reader)
    member_auth = Depends(require_member)

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
        caller: Caller = Depends(resolve_caller),
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

        When ``SEARCH_KEY_DAILY_TOKEN_QUOTA`` is positive, an API-key caller
        that has reached its daily token cap is rejected with HTTP 429 before
        the pipeline runs, and the completed query's tokens are recorded
        against the key. A cookie/browser caller (and the default disabled
        quota) skips both, doing no extra database work.
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
        quota = core.settings.SEARCH_KEY_DAILY_TOKEN_QUOTA
        # Pre-check BEFORE the pipeline so an over-quota key never spends a
        # token. A disabled quota or a cookie caller short-circuits with no I/O.
        try:
            await check_quota(
                api_key_id=caller.api_key_id,
                quota=quota,
                app_db_path=state.app_db_path,
            )
        except QuotaExceededError as exc:
            _raise_quota_429(exc)
        asker = resolve_asker(
            user.display_name,
            identity_aware=core.settings.SEARCH_IDENTITY_AWARE,
        )
        result = await _search(body, core, search_semaphore, asker=asker)
        # Record the completed query's total tokens against the key's daily
        # bucket (best-effort; a disabled quota / cookie caller records nothing).
        await record_usage(
            api_key_id=caller.api_key_id,
            quota=quota,
            tokens=result.cost.tokens.total,
            app_db_path=state.app_db_path,
        )
        # The recent-search write is a blocking multi-statement SQLite
        # transaction (delete+insert+trim); keep it off the loop too.
        await run_blocking(lambda: _record_recent_search(app_db, user, body.query))
        return result

    @router.post("/api/search/stream", response_model=None)
    async def search_stream(
        body: SearchRequest,
        state: AppState = Depends(get_app_state),
        caller: Caller = Depends(resolve_caller),
        _role: object = Depends(require_reader),
        user: CurrentUser = Depends(get_current_user),
    ) -> StreamingResponse:
        """Run the search pipeline and stream its live trace as NDJSON.

        The streaming twin of ``POST /api/search``: identical auth, core
        resolution, and concurrency bound, but instead of one JSON body it
        sends a sequence of newline-delimited JSON frames — a ``phase_start``
        then a ``phase_done`` per executed pipeline phase, then a terminal
        ``result`` (the full :class:`SearchResponse`) or ``error``. The SPA
        renders the phases live and folds them into a trace when the answer
        lands.

        ``response_model=None`` because the handler returns a hand-built
        :class:`StreamingResponse`, not a model FastAPI should derive a schema
        from. A successful search records the caller's recent search inside the
        worker thread (see :func:`_search_stream`), since the response body has
        already begun streaming by the time the pipeline finishes.

        The per-key spend quota is enforced identically to ``/api/search``: the
        pre-check runs here, before the body begins, so an over-quota key gets a
        clean HTTP 429; the post-record runs inside the worker once the total is
        known (see :func:`_search_stream`). Both are no-ops for a disabled quota
        or a cookie caller.
        """
        core = await run_blocking(lambda: resolve_core(state.app_db_path))
        search_semaphore.set_limit(core.settings.SEARCH_MAX_CONCURRENT)
        quota = core.settings.SEARCH_KEY_DAILY_TOKEN_QUOTA
        # Pre-check while a clean HTTP status is still possible — once the body
        # streams, the only failure channel is an error frame, never a 429.
        try:
            await check_quota(
                api_key_id=caller.api_key_id,
                quota=quota,
                app_db_path=state.app_db_path,
            )
        except QuotaExceededError as exc:
            _raise_quota_429(exc)
        asker = resolve_asker(
            user.display_name,
            identity_aware=core.settings.SEARCH_IDENTITY_AWARE,
        )
        return await _search_stream(
            body,
            core,
            search_semaphore,
            asker=asker,
            app_db_path=state.app_db_path,
            user=user,
            api_key_id=caller.api_key_id,
            quota=quota,
        )

    @router.get("/api/facets", dependencies=[reader_auth])
    async def facets() -> FacetsResponse:
        """Return taxonomy facets for the search UI filter panel.

        A 503 when the index schema is not present yet (or is mid-rebuild) — the
        same index-not-ready contract as the search and stats endpoints.
        """
        try:
            facet_set = await run_blocking(store_reader.list_facets)
        except SchemaNotReadyError as exc:
            log.info("api.facets_index_not_ready")
            raise HTTPException(
                status_code=503, detail="The search index is not ready"
            ) from exc
        return to_facets_response(facet_set)

    @router.get("/api/stats", dependencies=[reader_auth])
    async def stats() -> StatsResponse:
        """Return summary statistics for the search index.

        A 503 when the index schema is not present yet (or is mid-rebuild) — the
        same index-not-ready contract as the search and facets endpoints.
        """
        try:
            index_stats = await run_blocking(store_reader.get_stats)
        except SchemaNotReadyError as exc:
            log.info("api.stats_index_not_ready")
            raise HTTPException(
                status_code=503, detail="The search index is not ready"
            ) from exc
        return to_stats_response(index_stats)

    @router.get("/api/documents", dependencies=[reader_auth])
    async def documents(  # noqa: PLR0913 — one param per browse filter
        page: int = Query(default=1, ge=1, le=MAX_PAGE_NUMBER),
        page_size: int = Query(default=24, ge=1, le=MAX_PAGE_SIZE),
        sort: BrowseSort = Query(default="added"),
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
    body: SearchRequest,
    core: SearchCore,
    semaphore: LazySemaphore,
    *,
    asker: str | None = None,
) -> SearchResponse:
    """Search handler body: bound concurrency, convert filters, run off the loop.

    The concurrency semaphore caps simultaneous LLM spend (§10.6); the actual
    ``core.answer`` is CPU-light wiring around blocking I/O (LLM HTTP + SQLite),
    so ``run_in_executor`` keeps the event loop unblocked while it runs.

    The pipeline reads the live taxonomy (``list_facets``) at the top of every
    search, so a mid-rebuild window — where the indexer has dropped the schema
    and not yet recreated it — surfaces as a
    :class:`~store.SchemaNotReadyError`. That is mapped to a 503 "index not
    ready", the same contract as ``/api/facets``, ``/api/stats``, and the
    Library browse, rather than leaking a 500 on a transient rebuild.
    """
    ui_filters = to_search_filters(body.filters)

    async with semaphore.acquire():
        try:
            result = await run_blocking(
                lambda: core.answer(
                    query=body.query, ui_filters=ui_filters, asker=asker
                )
            )
        except SchemaNotReadyError as exc:
            log.info("api.search_index_not_ready")
            raise HTTPException(
                status_code=503, detail="The search index is not ready"
            ) from exc
    return to_search_response(result)


async def _search_stream(
    body: SearchRequest,
    core: SearchCore,
    semaphore: LazySemaphore,
    *,
    asker: str | None = None,
    app_db_path: str | None = None,
    user: CurrentUser | None = None,
    api_key_id: int | None = None,
    quota: int = 0,
) -> StreamingResponse:
    """Stream-search handler body: bridge the sync pipeline to an NDJSON stream.

    The pipeline (``core.answer``) is synchronous and blocking, but it emits
    live phase events through an ``on_event`` callback. To stream those without
    stalling the event loop, the pipeline runs on a worker thread while a
    bounded :class:`asyncio.Queue` carries its events back to the loop, which
    serialises each to an NDJSON line:

    - ``on_event`` (called on the worker thread) pushes each event onto the
      queue via :meth:`loop.call_soon_threadsafe` — the only thread-safe way to
      hand work to an asyncio object from another thread.
    - The worker (:func:`run`) runs ``core.answer``, then enqueues the result;
      a budget breach becomes a ``budget`` error frame, any other failure an
      ``internal`` one (logged with its traceback). A ``finally`` **always**
      enqueues the sentinel, so the drain loop is guaranteed to terminate even
      if the pipeline raises before emitting anything.
    - :func:`frames` drains the queue under the concurrency semaphore, assigning
      each frame a monotonically increasing ``seq``, and ``await``\\ s the worker
      in a ``finally`` so a client disconnect still reaps the thread.

    Recent-search recording **and** the per-key spend-quota record happen
    **inside the worker**, on the success path only: the response body has
    already begun streaming by the time the pipeline finishes, so the
    ``/api/search`` pattern of recording after the call in the handler is
    impossible here. Both writes use a **short-lived connection the worker opens
    from** ``app_db_path`` **and closes itself** — never the request's
    per-request ``app.db`` connection. That is what makes them race-free: on a
    client disconnect (the SPA aborts the stream on every new query) the event
    loop tears the request down and closes its own connection while this
    detached worker may still be finishing, but the two touch *different*
    connections, so there is no concurrent-use hazard on a
    ``check_same_thread=False`` connection. The recent-search write is
    best-effort and skipped when ``app_db_path``/``user`` are absent, as in the
    unit tests that drive this body directly; the usage record is best-effort
    and a no-op for a disabled quota or a cookie caller.

    Args:
        body: The validated search request.
        core: The resolved :class:`SearchCore`.
        semaphore: The shared concurrency bound (caps simultaneous LLM spend).
        asker: The identity-aware asker name, or ``None``.
        app_db_path: The filesystem path to ``app.db`` for recent-search and
            usage recording (the worker opens its own connection), or ``None``
            to skip recent-search recording (tests).
        user: The authenticated caller whose history the search is recorded
            against, or ``None`` to skip recent-search recording (tests).
        api_key_id: The caller's ``api_keys`` row id, or ``None`` for a cookie
            caller — usage is recorded only for an API key under a positive
            quota.
        quota: ``SEARCH_KEY_DAILY_TOKEN_QUOTA`` — ``0`` disables usage recording.

    Returns:
        A :class:`StreamingResponse` of ``application/x-ndjson`` frames.
    """
    ui_filters = to_search_filters(body.filters)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    sentinel = object()

    def on_event(event: object) -> None:
        """Forward one live phase event from the worker thread to the queue."""
        loop.call_soon_threadsafe(queue.put_nowait, ("event", event))

    def run() -> None:
        """Run the blocking pipeline on a worker thread, feeding the queue."""
        try:
            result = core.answer(
                query=body.query,
                ui_filters=ui_filters,
                asker=asker,
                on_event=on_event,
            )
            loop.call_soon_threadsafe(queue.put_nowait, ("result", result))
            # Record the recent search only on success, mirroring /api/search.
            # The worker opens, uses, and closes its OWN short-lived app.db
            # connection here (never the request's per-request connection), so a
            # client disconnect that closes the request connection on the loop
            # thread cannot race this write — they touch different connections.
            # Skipped when app_db_path/user are absent (the body is unit-tested
            # directly without a DB). Best-effort: any failure is logged and
            # swallowed so it never affects the already-streamed result.
            if app_db_path is not None and user is not None:
                try:
                    record_conn = connect(app_db_path)
                    try:
                        _record_recent_search(record_conn, user, body.query)
                    finally:
                        record_conn.close()
                except Exception:
                    log.exception("api.search_stream_record_failed")
            # Record the query's tokens against the API key's daily quota
            # bucket. record_usage_blocking is itself a no-op for a disabled
            # quota or a cookie caller and opens/closes its own connection, so
            # it is safe to call unconditionally once a DB path exists. It never
            # raises — a write fault degrades to a logged warning, never the
            # stream. Tests that drive this body without a DB pass app_db_path
            # None and skip it.
            if app_db_path is not None:
                record_usage_blocking(
                    api_key_id=api_key_id,
                    quota=quota,
                    tokens=result.stats.cost.tokens.total,
                    app_db_path=app_db_path,
                )
        except LlmBudgetExceededError as exc:
            loop.call_soon_threadsafe(queue.put_nowait, ("error", ("budget", str(exc))))
        except SchemaNotReadyError:
            # The index is mid-rebuild (schema dropped, not yet recreated). The
            # body has already begun streaming, so this cannot be a 503; surface
            # the same index-not-ready signal as a terminal error frame the SPA
            # can render distinctly from a generic failure.
            log.info("api.search_stream_index_not_ready")
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ("error", ("index_not_ready", "The search index is not ready")),
            )
        except Exception:
            # A streamed search cannot fail with an HTTP status once the body
            # has begun, so surface any pipeline fault as a terminal error
            # frame. log.exception attaches the traceback (§7.5).
            log.exception("api.search_stream_failed")
            loop.call_soon_threadsafe(
                queue.put_nowait, ("error", ("internal", "search failed"))
            )
        finally:
            # ALWAYS signal completion so the drain loop terminates, even if the
            # pipeline raised before emitting a single event.
            loop.call_soon_threadsafe(queue.put_nowait, ("sentinel", sentinel))

    async def frames() -> AsyncIterator[str]:
        """Drain the queue into ordered NDJSON lines until the sentinel."""
        async with semaphore.acquire():
            worker = loop.run_in_executor(None, run)
            seq = 0
            try:
                while True:
                    try:
                        kind, payload = await asyncio.wait_for(
                            queue.get(), timeout=_STREAM_KEEPALIVE_SECONDS
                        )
                    except asyncio.TimeoutError:
                        # No frame for a while (e.g. a long synthesiser call).
                        # Flush a blank line so idle proxies keep the connection
                        # open; the client skips blank lines.
                        yield "\n"
                        continue
                    if kind == "sentinel":
                        break
                    seq += 1
                    if kind == "event":
                        yield event_line(payload, seq)  # type: ignore[arg-type]
                    elif kind == "result":
                        yield result_line(to_search_response(payload), seq)  # type: ignore[arg-type]
                    elif kind == "error":
                        kind_msg = payload  # (kind, message)
                        yield error_line(kind_msg[0], kind_msg[1], seq)  # type: ignore[index]
            finally:
                # Reap the worker so a client disconnect (generator close) does
                # not leak the thread; run() swallows its own exceptions, so
                # this await never raises.
                await worker

    return StreamingResponse(frames(), media_type="application/x-ndjson")


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
    sort: BrowseSort,
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

    ``sort`` is a :data:`~search.wire.BrowseSort`, validated to the allowed set
    at the ``Query`` boundary, so :func:`to_document_browse_query` cannot fail
    on it — no runtime guard is needed here (SRCH-11).  An index with no schema
    yet surfaces as a 503, consistent with the index-not-ready contract; any
    other store fault propagates as a 500.
    """
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
        paperless_base_url=settings.PAPERLESS_PUBLIC_URL.rstrip("/"),
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
        # log.exception attaches the active traceback (§7.5) so a recurring DB
        # fault on this best-effort side path is debuggable, not just counted.
        log.exception("api.recent_search_record_failed", user_id=user.id)
