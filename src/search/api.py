"""FastAPI search server: the API routers, ``/mcp`` and the built SPA.

Browser auth is a server-side session behind an opaque, hashed cookie;
programmatic access uses ``sk-pls-...`` bearer API keys. The index DB is never
web-reachable: static serving is rooted only at the built frontend directory.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog
import uvicorn
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from appdb.connection import connect as connect_app_db
from appdb.model_pricing import load_cached_prices, save_cached_prices
from appdb.schema import ensure_schema as ensure_app_db_schema
from common.concurrency import llm_limiter
from common.heartbeat import Heartbeat, run_heartbeat_ticker
from common.library_setup import setup_libraries
from common.shutdown import is_shutdown_requested
from search.pricing_book import (
    PricingRefreshError,
    price_book_from_cache,
    refresh_price_book,
    set_current_price_book,
    to_cached_table,
)
from search.account_routes import build_account_router
from search.api_key_routes import build_api_key_router
from search.appdb_setup import open_app_db
from search.appstate import AppState, attach_app_state
from search.body_limit import BodyLimitMiddleware
from search.deps import get_current_user, require_api_scope, require_api_scope_member
from search.document_routes import build_document_router
from search.fetch_site import FetchSiteMiddleware
from search.index_routes import build_index_router
from search.mcp_server import build_mcp_app
from search.offload import LazySemaphore
from search.routes import build_api_router
from search.security_headers import SecurityHeadersMiddleware
from search.settings_routes import build_settings_router
from search.setup import SetupState, generate_setup_token, is_setup_needed
from search.spa import register_spa

if TYPE_CHECKING:
    from common.config import Settings
    from search.core import SearchCore
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

# FRONTEND_DIST is set by the Dockerfile; the fallback serves a source checkout.
# A missing directory makes the SPA mount a no-op.
_env_frontend = os.environ.get("FRONTEND_DIST", "").strip()
if _env_frontend:
    _FRONTEND_DIST = Path(_env_frontend)
else:
    _REPO_ROOT = Path(__file__).parent.parent.parent
    _FRONTEND_DIST = _REPO_ROOT / "web" / "dist"

# Well inside appdb.daemon_status.DEFAULT_STALE_AFTER_SECONDS so the dashboard
# never flickers the server to "stopped" between beats.
_SEARCH_HEARTBEAT_INTERVAL_SECONDS = 30


def _start_search_heartbeat(settings: Settings) -> Callable[[], None]:
    """Start the search server's heartbeat thread; return its stop callable.

    The per-app stop event gives each app instance ownership of its thread, so
    an app built in a test does not leak a ticker for the rest of the process.
    The heartbeat is best-effort: if ``app.db`` cannot be opened it is skipped
    and only the dashboard's "search" tile goes stale.
    """
    stop_event = threading.Event()

    def _stop_aware_sleep(seconds: float) -> None:
        stop_event.wait(seconds)

    def _run() -> None:
        try:
            conn = connect_app_db(settings.APP_DB_PATH)
            ensure_app_db_schema(conn)
        except Exception as exc:  # noqa: BLE001
            log.warning("api.heartbeat_disabled", error=str(exc))
            return
        heartbeat = Heartbeat(name="search", conn=conn)
        try:
            run_heartbeat_ticker(
                heartbeat,
                detail_fn=lambda: "serving search requests",
                interval_seconds=_SEARCH_HEARTBEAT_INTERVAL_SECONDS,
                should_stop=lambda: stop_event.is_set() or is_shutdown_requested(),
                sleep=_stop_aware_sleep,
            )
        finally:
            conn.close()

    thread = threading.Thread(target=_run, name="search-heartbeat", daemon=True)
    thread.start()
    log.info("api.heartbeat_started")

    def _stop() -> None:
        stop_event.set()
        thread.join(timeout=5)

    return _stop


# How often the price-refresh thread checks the shutdown flag. The refresh
# cadence itself is PRICING_REFRESH_INTERVAL_HOURS.
_PRICE_REFRESH_TICK_SECONDS = 60


def _load_cached_price_book(app_db_path: str) -> None:
    """Set the live price book from the app.db cache, if one exists.

    Runs once at startup, before any refresh. With an empty cache the bundled
    seed stands. A failed cache read is logged and ignored so it never aborts
    startup.
    """
    try:
        conn = connect_app_db(app_db_path)
        try:
            cached = load_cached_prices(conn)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("api.price_cache_load_failed", error=str(exc))
        return
    if cached is None:
        return
    set_current_price_book(price_book_from_cache(cached))
    log.info(
        "api.price_cache_loaded",
        source=cached.source,
        as_of=cached.as_of,
        model_count=len(cached.table),
    )


def _start_price_refresh(settings: Settings, app_db_path: str) -> None:
    """Start the background price-refresh thread when a URL is configured.

    With ``PRICING_REFRESH_URL`` empty (the default) no thread starts and no
    network call is made. Otherwise the thread fetches at once, then every
    ``PRICING_REFRESH_INTERVAL_HOURS`` until shutdown.
    """
    url = settings.PRICING_REFRESH_URL
    if not url:
        return

    interval_seconds = settings.PRICING_REFRESH_INTERVAL_HOURS * 3600

    def _run() -> None:
        _refresh_once(url, app_db_path)
        # Short ticks so shutdown is honoured promptly, not after a multi-hour
        # sleep.
        next_refresh = time.monotonic() + interval_seconds
        while not is_shutdown_requested():
            time.sleep(_PRICE_REFRESH_TICK_SECONDS)
            if is_shutdown_requested():
                return
            if time.monotonic() >= next_refresh:
                _refresh_once(url, app_db_path)
                next_refresh = time.monotonic() + interval_seconds

    thread = threading.Thread(target=_run, name="search-price-refresh", daemon=True)
    thread.start()
    log.info(
        "api.price_refresh_started",
        source=url,
        interval_hours=settings.PRICING_REFRESH_INTERVAL_HOURS,
    )


def _refresh_once(url: str, app_db_path: str) -> None:
    """Fetch the price book from *url* once; persist and publish on success.

    A fetch or parse failure keeps the current book. A failure persisting the
    cache is logged, and the fetched book is still published.
    """
    try:
        book = refresh_price_book(url)
    except PricingRefreshError as exc:
        log.warning("api.price_refresh_failed", source=url, error=str(exc))
        return
    try:
        conn = connect_app_db(app_db_path)
        try:
            save_cached_prices(
                conn,
                table=to_cached_table(book),
                as_of=book.as_of,
                source=book.source,
                fetched_at=book.fetched_at,
            )
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        # Only storage errors are swallowed; a logic bug still surfaces.
        log.warning("api.price_cache_save_failed", source=url, error=str(exc))
    set_current_price_book(book)
    log.info("api.price_refreshed", source=url, as_of=book.as_of)


def register_paperless_exception_handlers(app: FastAPI) -> None:
    """Map ``httpx`` errors escaping a route handler to meaningful statuses.

    Upstream 404 and 409 pass through; 5xx, 401, 403 and network errors become
    502 (the server's own token was rejected or lacks permission, which the
    browser must not read as "log in"). The streaming PDF/thumbnail handlers answer a 404
    and other upstream statuses themselves, and pass a 401 or 403 on to these handlers.
    """

    @app.exception_handler(httpx.HTTPStatusError)
    async def _paperless_http_error(  # noqa: RUF029 — must be async for FastAPI handler protocol
        request: Request,
        exc: httpx.HTTPStatusError,
    ) -> JSONResponse:
        status = exc.response.status_code
        if status == 404:
            return JSONResponse(
                status_code=404,
                content={"detail": "not found in Paperless-ngx"},
            )
        if status == 409:
            return JSONResponse(
                status_code=409,
                content={"detail": "conflict in Paperless-ngx"},
            )
        if status in (401, 403):
            log.warning(
                "paperless.token_rejected"
                if status == 401
                else "paperless.permission_denied",
                status=status,
            )
            detail = (
                "Paperless-ngx rejected the server's API token"
                if status == 401
                else "Paperless-ngx denied the server's API token permission for this request"
            )
            return JSONResponse(status_code=502, content={"detail": detail})
        if status >= 500:
            log.warning("paperless.upstream_error", status=status)
            return JSONResponse(
                status_code=502,
                content={"detail": "Paperless-ngx upstream error"},
            )
        log.warning("paperless.http_error", status=status)
        return JSONResponse(
            status_code=status,
            content={"detail": "Paperless-ngx returned an error"},
        )

    @app.exception_handler(httpx.RequestError)
    async def _paperless_network_error(  # noqa: RUF029
        request: Request,
        exc: httpx.RequestError,
    ) -> JSONResponse:
        log.warning("paperless.network_error", error=str(exc))
        return JSONResponse(
            status_code=502,
            content={"detail": "Could not reach Paperless-ngx"},
        )


def create_app(
    settings: Settings,
    *,
    core: SearchCore | None = None,
    store_reader: StoreReader | None = None,
    app_db_path: str | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    The app holds the ``app.db`` path, not a connection: each request opens its
    own, because a ``sqlite3.Connection`` cannot be shared across the threads
    FastAPI serves requests on. *core* and *store_reader* are built from
    *settings* when not supplied.
    """
    core, store_reader = _resolve_components(settings, core, store_reader)
    app_db_path = settings.APP_DB_PATH if app_db_path is None else app_db_path

    # Shared by HTTP search and the MCP tools so SEARCH_MAX_CONCURRENT is one cap,
    # not one per surface.
    search_semaphore = LazySemaphore(settings.SEARCH_MAX_CONCURRENT)

    # An attached ASGI sub-app's lifespan never runs, so the lifespan below must
    # run the MCP session manager or every /mcp request fails with "Task group
    # is not initialized".
    mcp_app = build_mcp_app(
        _resolve_search_core,
        app_db_path,
        search_semaphore=search_semaphore,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # The heartbeat starts here rather than in create_app() so building an
        # app starts no thread.
        stop_heartbeat = _start_search_heartbeat(settings)
        try:
            async with mcp_app.session_manager.run():
                yield
        finally:
            stop_heartbeat()

    app = FastAPI(
        title="Paperless Semantic Search",
        docs_url=None,
        redoc_url=None,
        # /openapi.json would otherwise still be served and list every route and
        # model; nothing first-party consumes it.
        openapi_url=None,
        lifespan=lifespan,
    )

    # The last one added is outermost: security headers wrap everything,
    # including /mcp, the SPA and the body limit's own 413.
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(FetchSiteMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    register_paperless_exception_handlers(app)

    setup_state = SetupState()
    startup_conn = open_app_db(app_db_path)
    try:
        if is_setup_needed(startup_conn):
            setup_state.token = generate_setup_token()
            log.warning(
                "search.setup_mode",
                message=(
                    f"SETUP TOKEN: {setup_state.token} — open /setup to create "
                    "the first admin account"
                ),
            )
    finally:
        startup_conn.close()

    _load_cached_price_book(app_db_path)

    attach_app_state(
        app.state,
        AppState(app_db_path=app_db_path, setup_state=setup_state),
    )

    _seed_core_cache(app_db_path, core)

    def current_settings() -> Settings:
        live_core = _resolve_search_core(app_db_path)
        # Until a settings save replaces the startup core, the live settings are
        # the ones this app was built with; a caller may pass them apart from it.
        return settings if live_core is core else live_core.settings

    # An exact-path Route, not app.mount: a Mount only serves "/mcp/..." and the
    # SPA catch-all would 405 the bare "/mcp" instead of Starlette redirecting.
    # Registered before the other routers and the catch-all so it wins.
    app.router.routes.append(Route("/mcp", mcp_app))
    app.include_router(build_account_router(settings, store_reader))
    app.include_router(build_settings_router(settings))
    app.include_router(build_api_key_router())
    app.include_router(
        build_document_router(
            current_settings,
            store_reader=store_reader,
        )
    )
    app.include_router(build_index_router(settings, store_reader))
    app.include_router(
        build_api_router(
            settings,
            _resolve_search_core,
            store_reader,
            require_reader=require_api_scope,
            require_member=require_api_scope_member,
            get_current_user=get_current_user,
            search_semaphore=search_semaphore,
            current_settings=current_settings,
        )
    )

    register_spa(app, _FRONTEND_DIST)
    _start_price_refresh(settings, app_db_path)
    return app


def _resolve_components(
    settings: Settings,
    core: SearchCore | None,
    store_reader: StoreReader | None,
) -> tuple[SearchCore, StoreReader]:
    """Return the core and store reader, building any not supplied by a caller."""
    if core is not None and store_reader is not None:
        return core, store_reader

    from common.embeddings import EmbeddingClient
    from search.core import SearchCore
    from search.judge import RelevanceJudge
    from search.planner import QueryPlanner
    from search.retriever import Retriever
    from search.synthesizer import Synthesizer
    from store.reader import StoreReader as _StoreReader

    if store_reader is None:
        store_reader = _StoreReader(settings)
    if core is None:
        embedding_client = EmbeddingClient(settings)
        retriever = Retriever(settings, store_reader, embedding_client)
        core = SearchCore(
            settings,
            store_reader,
            QueryPlanner(settings),
            retriever,
            Synthesizer(settings),
            RelevanceJudge(settings),
        )
    return core, store_reader


# app.db path -> (config_version, core); rebuilt only when the config changes.
_CORE_CACHE: dict[str, tuple[int, "SearchCore"]] = {}

# Gates only the rebuild, so concurrent callers on a new config_version do not
# both build a core; the lookup stays lock-free.
_CORE_CACHE_LOCK = threading.Lock()


def _resolve_search_core(app_db_path: str) -> SearchCore:
    """Return the search core for the current configuration, rebuilt on change.

    Called per request; a steady-state call costs one ``config_version`` read.
    A rebuild also re-initialises the process-wide OpenAI client holder and LLM
    limiter, so a saved provider, key or concurrency change reaches every LLM
    call on the next request.
    """
    from appdb import config as config_store  # noqa: PLC0415
    from appdb.connection import connect  # noqa: PLC0415
    from appdb.schema import ensure_schema  # noqa: PLC0415
    from common.config import current_settings_with_version  # noqa: PLC0415
    from search.cache import reset_search_result_cache  # noqa: PLC0415

    conn = connect(app_db_path)
    try:
        ensure_schema(conn)
        version = config_store.get_config_version(conn)
    finally:
        conn.close()

    cached = _CORE_CACHE.get(app_db_path)
    if cached is not None and cached[0] == version:
        return cached[1]

    with _CORE_CACHE_LOCK:
        # Re-check inside the lock: another caller may have rebuilt while we
        # were waiting.
        cached = _CORE_CACHE.get(app_db_path)
        if cached is not None and cached[0] == version:
            return cached[1]

        # Read version and settings in one snapshot: a write landing between two
        # reads could stamp a newer version onto an older core and pin the stale
        # core in the cache.
        cache_version, settings = current_settings_with_version(app_db_path)
        # A config change can alter the answer to an identical query (model,
        # top-k, prompts, ...), and the result cache is keyed only on the index
        # version, so drop it rather than serve pre-change answers until the TTL.
        # Dropped before the build: a core stamps the cache generation it is
        # built under and uses the cache only while that generation holds.
        reset_search_result_cache()
        setup_libraries(settings)
        llm_limiter.init(settings.LLM_MAX_CONCURRENT)
        core, _store_reader = _resolve_components(settings, None, None)
        _CORE_CACHE[app_db_path] = (cache_version, core)
        return core


def _reset_core_cache_for_test() -> None:
    """Clear the process-local search-core cache — for tests only."""
    _CORE_CACHE.clear()


def _seed_core_cache(app_db_path: str, core: SearchCore) -> None:
    """Prime the core cache with the startup-built *core*."""
    from appdb import config as config_store  # noqa: PLC0415
    from appdb.connection import connect  # noqa: PLC0415

    conn = connect(app_db_path)
    try:
        version = config_store.get_config_version(conn)
    finally:
        conn.close()
    _CORE_CACHE[app_db_path] = (version, core)


def main() -> None:
    """Start the search server (entry point: ``paperless-search-server``).

    ``proxy_headers=True`` makes the request scheme and client IP reflect the
    reverse proxy's forwarded values, so the session cookie gets ``Secure`` and
    ``sessions.ip`` records the real client. ``SEARCH_FORWARDED_ALLOW_IPS``
    defaults to ``"*"``, which is only safe when the uvicorn port is reachable
    solely by the proxy; otherwise pin it to the proxy's address so the
    forwarded headers cannot be spoofed.
    """
    from common.bootstrap import bootstrap_process

    settings = bootstrap_process()

    try:
        app = create_app(settings)
    except Exception:
        # E.g. an app.db written by newer code: abort rather than serve a
        # half-built app.
        log.exception("search.startup_failed")
        sys.exit(1)

    log.info(
        "search_server.starting",
        host=settings.SEARCH_SERVER_HOST,
        port=settings.SEARCH_SERVER_PORT,
    )
    uvicorn.run(
        app,
        host=settings.SEARCH_SERVER_HOST,
        port=settings.SEARCH_SERVER_PORT,
        proxy_headers=True,
        forwarded_allow_ips=settings.SEARCH_FORWARDED_ALLOW_IPS,
    )
