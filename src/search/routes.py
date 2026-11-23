"""The search server's ``/api`` routes: healthz, search, facets, stats, browse
and the reconcile trigger."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
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
from search.core import TokenTally
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
from search.wire.search import FILTER_ID_MAX, FILTER_ID_MIN, FilterId
from search.wire.stream import error_line, event_line, result_line
from store import SchemaNotReadyError, StoreError

if TYPE_CHECKING:
    from common.config import Settings
    from search.core import SearchCore
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

# Written next to the index DB; the indexer's polling loop picks it up.
_RECONCILE_SENTINEL_NAME = "reconcile.request"

_HEALTHZ_UNAVAILABLE_STATUS = 503

_QUOTA_EXCEEDED_STATUS = 429

_QUOTA_EXCEEDED_MESSAGE = (
    "Daily LLM token quota for this API key has been reached. "
    "It resets at UTC midnight."
)

# One LLM call (e.g. synthesis) can run 40s+ with nothing to send, and an idle
# proxy or tunnel would close the connection. A blank NDJSON line keeps it open;
# the client skips blank lines.
_STREAM_KEEPALIVE_SECONDS = 15.0

IndexHealthState = Literal["ok", "index-not-ready", "index-corrupt"]


@dataclass(frozen=True, slots=True)
class IndexHealth:
    """The outcome of an index-health evaluation.

    ``reason`` is a short machine-readable cause for the log; empty when ok.
    """

    state: IndexHealthState
    reason: str


_INDEX_HEALTHY = IndexHealth(state="ok", reason="")


def evaluate_index_health(store_reader: StoreReader) -> IndexHealth:
    """Evaluate the index's health; the caller has checked the DB file exists.

    ``ok`` needs the schema, at least one completed reconcile and a clean
    ``quick_check``. A missing schema, no reconcile yet or a stats failure is
    ``index-not-ready``; a failed ``quick_check`` is ``index-corrupt``.
    """
    try:
        stats = store_reader.get_stats()
    except SchemaNotReadyError:
        return IndexHealth(state="index-not-ready", reason="schema_missing")
    except StoreError as exc:
        return IndexHealth(state="index-not-ready", reason=f"stats_error: {exc}")

    if stats.last_reconcile_at is None:
        return IndexHealth(state="index-not-ready", reason="never_reconciled")

    try:
        integrity_ok = store_reader.quick_check()
    except StoreError:
        integrity_ok = False

    if not integrity_ok:
        return IndexHealth(state="index-corrupt", reason="quick_check_failed")

    return _INDEX_HEALTHY


def _health_response(state: IndexHealthState) -> Response:
    """Build the healthz response: 200 when ok, else 503 so the Docker
    healthcheck marks the container unhealthy."""
    status_code = 200 if state == "ok" else _HEALTHZ_UNAVAILABLE_STATUS
    return Response(
        content=f'{{"status":"{state}"}}',
        status_code=status_code,
        media_type="application/json",
    )


def _seconds_to_next_utc_midnight(now: datetime) -> int:
    """Return whole seconds until the next UTC midnight, when the quota refills.

    At least 1, so a request in the day's final second is not told to retry
    immediately.
    """
    tomorrow = (now + timedelta(days=1)).date()
    next_midnight = datetime(
        tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc
    )
    return max(1, int((next_midnight - now).total_seconds()))


def _raise_quota_429(exc: QuotaExceededError) -> None:
    """Raise an HTTP 429 whose ``Retry-After`` points at the next UTC midnight."""
    retry_after = _seconds_to_next_utc_midnight(datetime.now(timezone.utc))
    raise HTTPException(
        status_code=_QUOTA_EXCEEDED_STATUS,
        detail=_QUOTA_EXCEEDED_MESSAGE,
        headers={"Retry-After": str(retry_after)},
    ) from exc


async def _check_quota_or_429(
    *, api_key_id: int | None, quota: int, app_db_path: str
) -> None:
    """Run :func:`check_quota`, turning a refusal into the HTTP 429."""
    try:
        await check_quota(api_key_id=api_key_id, quota=quota, app_db_path=app_db_path)
    except QuotaExceededError as exc:
        _raise_quota_429(exc)


def build_api_router(
    settings: Settings,
    resolve_core: Callable[[str], SearchCore],
    store_reader: StoreReader,
    *,
    require_reader: Callable[..., CurrentUser],
    require_member: Callable[..., CurrentUser],
    get_current_user: Callable[..., CurrentUser],
    search_semaphore: LazySemaphore,
    current_settings: Callable[[], Settings],
) -> APIRouter:
    """Build the ``/api`` router.

    ``/api/healthz`` is unauthenticated; the reconcile trigger needs Member or
    above and the rest Read-only or above. *resolve_core* is called per request
    so a saved configuration change applies without a restart.
    *search_semaphore* is shared with the MCP tools so ``SEARCH_MAX_CONCURRENT``
    is one cap across both. *current_settings* is called per request for the
    Library's Paperless links.
    """
    router = APIRouter()
    reader_auth = Depends(require_reader)
    member_auth = Depends(require_member)

    @router.get("/api/healthz", response_model=None)
    async def healthz() -> Response:
        """Liveness check; surfaces index state to the Docker healthcheck.

        Offloaded because ``PRAGMA quick_check`` scans the whole database.
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

        An API-key caller over its daily token quota gets a 429 before the
        pipeline runs. A successful search is added to the caller's recent
        searches.
        """
        core = await run_blocking(lambda: resolve_core(state.app_db_path))
        search_semaphore.set_limit(core.settings.SEARCH_MAX_CONCURRENT)
        quota = core.settings.SEARCH_KEY_DAILY_TOKEN_QUOTA
        # Checked early for a fast 429; _search checks again once it holds a slot.
        await _check_quota_or_429(
            api_key_id=caller.api_key_id, quota=quota, app_db_path=state.app_db_path
        )
        asker = resolve_asker(
            user.display_name,
            identity_aware=core.settings.SEARCH_IDENTITY_AWARE,
        )
        result = await _search(
            body,
            core,
            search_semaphore,
            asker=asker,
            app_db_path=state.app_db_path,
            api_key_id=caller.api_key_id,
            quota=quota,
        )
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

        Same auth, quota and concurrency bound as ``POST /api/search``. Frames
        are a ``phase_start`` and ``phase_done`` per phase, then a terminal
        ``result`` or ``error``.
        """
        core = await run_blocking(lambda: resolve_core(state.app_db_path))
        search_semaphore.set_limit(core.settings.SEARCH_MAX_CONCURRENT)
        quota = core.settings.SEARCH_KEY_DAILY_TOKEN_QUOTA
        # Pre-check while a clean HTTP status is still possible — once the body
        # streams, the only failure channel is an error frame, never a 429.
        await _check_quota_or_429(
            api_key_id=caller.api_key_id, quota=quota, app_db_path=state.app_db_path
        )
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
        """Return taxonomy facets for the filter panel; 503 while the index is
        not ready."""
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
        """Return summary statistics for the index; 503 while it is not ready."""
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
        correspondent_id: int | None = Query(
            default=None, ge=FILTER_ID_MIN, le=FILTER_ID_MAX
        ),
        document_type_id: int | None = Query(
            default=None, ge=FILTER_ID_MIN, le=FILTER_ID_MAX
        ),
        tag_ids: list[FilterId] = Query(default_factory=list, max_length=64),
        date_from: str | None = Query(default=None),
        date_to: str | None = Query(default=None),
    ) -> DocumentListResponse:
        """List indexed documents for the Library, paginated.

        ``query`` is a case-insensitive match over title, correspondent and
        document type; ``added`` sorts by date indexed.
        """
        return await _documents(
            await run_blocking(current_settings),
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
        """Touch the reconcile sentinel for the indexer and return 202.

        Writes only the sentinel, never the index DB.
        """
        return _reconcile(settings)

    return router


def _healthz(settings: Settings, store_reader: StoreReader) -> Response:
    """Liveness handler body: file check, then the three-state evaluation."""
    db_path = Path(settings.INDEX_DB_PATH)
    if not db_path.exists():
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
    asker: str | None,
    app_db_path: str,
    api_key_id: int | None,
    quota: int,
) -> SearchResponse:
    """Run ``core.answer`` off the loop under the concurrency bound.

    The quota is checked again once the slot is held, since requests that
    passed the early check together may have spent it while waiting. The
    search's tokens are then charged to the API key; a cached answer is free,
    and a failed one is charged for the phases it finished.

    A search during an index rebuild hits a missing schema; that becomes a 503
    like the other index-not-ready endpoints, not a 500.
    """
    ui_filters = to_search_filters(body.filters)
    cache_hits: list[None] = []
    spent = TokenTally()

    async with semaphore.acquire():
        await _check_quota_or_429(
            api_key_id=api_key_id, quota=quota, app_db_path=app_db_path
        )
        try:
            result = await run_blocking(
                lambda: core.answer(
                    query=body.query,
                    ui_filters=ui_filters,
                    asker=asker,
                    on_event=spent,
                    on_cache_hit=lambda: cache_hits.append(None),
                )
            )
        except Exception as exc:
            if spent.total:
                await record_usage(
                    api_key_id=api_key_id,
                    quota=quota,
                    tokens=spent.total,
                    app_db_path=app_db_path,
                )
            if isinstance(exc, SchemaNotReadyError):
                log.info("api.search_index_not_ready")
                raise HTTPException(
                    status_code=503, detail="The search index is not ready"
                ) from exc
            raise
        # Recorded before the slot is freed so the next waiter's check sees it.
        await record_usage(
            api_key_id=api_key_id,
            quota=quota,
            tokens=0 if cache_hits else result.stats.cost.tokens.total,
            app_db_path=app_db_path,
        )
    return to_search_response(result)


def _release_slot(slot: AbstractAsyncContextManager[None]) -> None:
    """Free a slot from :meth:`LazySemaphore.acquire` without awaiting.

    The unbounded no-op slot holds nothing to free.
    """
    if isinstance(slot, asyncio.Semaphore):
        slot.release()


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
    """Run the blocking pipeline on a worker thread and stream its events.

    The worker hands events to the loop through ``call_soon_threadsafe`` and
    always enqueues a sentinel, so the drain loop ends even if the pipeline
    raises early.

    The body is already streaming when the pipeline finishes, so the worker
    records the recent search and token usage itself, on its own short-lived
    ``app.db`` connection. The SPA aborts the stream on every new query, and
    the loop then closes the request's connection while this worker may still
    be running; separate connections avoid that race. ``app_db_path=None``
    skips both writes and the quota re-check. A pipeline that fails is still
    charged for the phases it finished.

    The search slot is released when the worker ends, not when the client
    goes: an abandoned pipeline keeps running and spending tokens. Once the
    slot is held the quota is checked again; a refusal is a ``quota`` error
    frame.
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
        cache_hits: list[None] = []
        spent = TokenTally(on_event)
        answered = False
        try:
            result = core.answer(
                query=body.query,
                ui_filters=ui_filters,
                asker=asker,
                on_event=spent,
                on_cache_hit=lambda: cache_hits.append(None),
            )
            answered = True
            loop.call_soon_threadsafe(queue.put_nowait, ("result", result))
            if app_db_path is not None and user is not None:
                try:
                    record_conn = connect(app_db_path)
                    try:
                        _record_recent_search(record_conn, user, body.query)
                    finally:
                        record_conn.close()
                except Exception:
                    log.exception("api.search_stream_record_failed")
            if app_db_path is not None:
                record_usage_blocking(
                    api_key_id=api_key_id,
                    quota=quota,
                    tokens=0 if cache_hits else result.stats.cost.tokens.total,
                    app_db_path=app_db_path,
                )
        except LlmBudgetExceededError as exc:
            loop.call_soon_threadsafe(queue.put_nowait, ("error", ("budget", str(exc))))
        except SchemaNotReadyError:
            # Too late for a 503 once streaming; a distinct frame lets the SPA
            # tell a rebuild from a failure.
            log.info("api.search_stream_index_not_ready")
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ("error", ("index_not_ready", "The search index is not ready")),
            )
        except Exception:
            log.exception("api.search_stream_failed")
            loop.call_soon_threadsafe(
                queue.put_nowait, ("error", ("internal", "search failed"))
            )
        finally:
            if not answered and app_db_path is not None and spent.total:
                record_usage_blocking(
                    api_key_id=api_key_id,
                    quota=quota,
                    tokens=spent.total,
                    app_db_path=app_db_path,
                )
            loop.call_soon_threadsafe(queue.put_nowait, ("sentinel", sentinel))

    async def frames() -> AsyncIterator[str]:
        """Drain the queue into ordered NDJSON lines until the sentinel."""
        slot = semaphore.acquire()
        await slot.__aenter__()
        try:
            if app_db_path is not None:
                await check_quota(
                    api_key_id=api_key_id, quota=quota, app_db_path=app_db_path
                )
            worker = loop.run_in_executor(None, run)
        except BaseException as exc:
            await slot.__aexit__(None, None, None)
            if isinstance(exc, QuotaExceededError):
                yield error_line("quota", _QUOTA_EXCEEDED_MESSAGE, 1)
            elif isinstance(exc, Exception):
                log.exception("api.search_stream_failed")
                yield error_line("internal", "search failed", 1)
            else:
                raise
            return
        worker.add_done_callback(lambda _: _release_slot(slot))
        seq = 0
        while True:
            try:
                kind, payload = await asyncio.wait_for(
                    queue.get(), timeout=_STREAM_KEEPALIVE_SECONDS
                )
            except asyncio.TimeoutError:
                yield "\n"
                continue
            if kind == "sentinel":
                break
            if kind == "event":
                try:
                    line = event_line(payload, seq + 1)  # type: ignore[arg-type]
                except Exception:
                    # A trace frame is only progress; dropping it keeps the
                    # stream going to its result or error frame.
                    log.exception("api.search_stream_serialise_failed")
                    continue
                seq += 1
                yield line
                continue
            seq += 1
            if kind == "result":
                try:
                    line = result_line(to_search_response(payload), seq)  # type: ignore[arg-type]
                except Exception:
                    log.exception("api.search_stream_serialise_failed")
                    line = error_line("internal", "search failed", seq)
                yield line
            elif kind == "error":
                kind_msg = payload  # (kind, message)
                yield error_line(kind_msg[0], kind_msg[1], seq)  # type: ignore[index]

    return StreamingResponse(frames(), media_type="application/x-ndjson")


def _reconcile(settings: Settings) -> Response:
    """Reconcile handler body: touch the sentinel, return 202 Accepted.

    An unwritable sentinel directory is a misconfigured ``INDEX_DB_PATH``, so it
    is a 503 like the rebuild trigger's, not a generic 500.
    """
    db_dir = Path(settings.INDEX_DB_PATH).parent
    sentinel = db_dir / _RECONCILE_SENTINEL_NAME
    try:
        sentinel.touch()
    except OSError as exc:
        log.error(
            "api.reconcile_sentinel_write_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="cannot write sentinel: index data directory not writable",
        ) from exc
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
    """Run the Library browse query off the loop; 503 while the index is not
    ready."""
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
    """Record a search in the caller's history; a failure is logged, not raised."""
    try:
        recent_search_store.record(app_db, user_id=user.id, query=query)
    except Exception:
        log.exception("api.recent_search_record_failed", user_id=user.id)
