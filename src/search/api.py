"""FastAPI search server — HTTP API, account management, SPA, and MCP mount.

One uvicorn process serves:
- the account endpoints (setup, login/logout/me, user CRUD) — ``account_routes``
- the search endpoints (search, facets, stats, reconcile, healthz) — ``routes``
- ``/mcp``  — the MCP streamable-HTTP ASGI app
- ``/``     — the built React SPA, with a deep-link catch-all

This module is component wiring only: build the core, migrate ``app.db`` (a
short-lived startup connection), enter setup mode if there are no users,
attach the per-app account context, mount the routers and the SPA. Each
request opens its own ``app.db`` connection — see :mod:`search.deps`.

Security invariants (web-redesign §4; CODE_GUIDELINES §10):
- Browser auth is a server-side session behind an opaque, hashed cookie.
- Programmatic access is by ``Authorization: Bearer sk-pls-...`` API keys,
  looked up in ``app.db`` and bounded by their scopes and owner's role.
  ``SEARCH_API_KEY`` is retired (web-redesign §5).
- The index DB is never web-reachable — static serving is rooted only at the
  built frontend directory.

Allowed deps: fastapi, uvicorn, starlette, search (routes, account_routes,
    deps, appstate, setup, spa, appdb_setup, mcp_server, core), store
    (reader), appdb, common.config.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import uvicorn
from fastapi import FastAPI

from appdb.connection import connect as connect_app_db
from appdb.schema import ensure_schema as ensure_app_db_schema
from common.concurrency import llm_limiter
from common.heartbeat import Heartbeat, run_heartbeat_ticker
from common.library_setup import setup_libraries
from common.shutdown import is_shutdown_requested
from search.account_routes import build_account_router
from search.api_key_routes import build_api_key_router
from search.appdb_setup import open_app_db
from search.appstate import AppState, attach_app_state
from search.deps import get_current_user, require_api_scope, require_api_scope_member
from search.document_routes import build_document_router
from search.index_routes import build_index_router
from search.mcp_server import build_mcp_app
from search.routes import build_api_router
from search.settings_routes import build_settings_router
from search.setup import SetupState, generate_setup_token, is_setup_needed
from search.spa import register_spa

if TYPE_CHECKING:
    from common.config import Settings
    from search.core import SearchCore
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

# Path to the built frontend. Resolution order: the FRONTEND_DIST env var
# (set by the Dockerfile), else the path relative to the repo root for
# source-tree execution. Resolved at import time; a missing directory makes
# the SPA mount a no-op rather than crashing the server.
_env_frontend = os.environ.get("FRONTEND_DIST", "").strip()
if _env_frontend:
    _FRONTEND_DIST = Path(_env_frontend)
else:
    _REPO_ROOT = Path(__file__).parent.parent.parent
    _FRONTEND_DIST = _REPO_ROOT / "web" / "dist"

# How often the search server writes its daemon-status heartbeat, in
# seconds. Comfortably inside appdb.daemon_status.DEFAULT_STALE_AFTER_SECONDS
# so the dashboard never flickers the server to "stopped" between beats.
_SEARCH_HEARTBEAT_INTERVAL_SECONDS = 30


def _start_search_heartbeat(settings: Settings) -> None:
    """Start the background thread that writes the search server's heartbeat.

    The search server has no polling loop, so it heartbeats from a daemon
    thread: it beats every ``_SEARCH_HEARTBEAT_INTERVAL_SECONDS`` until the
    shared shutdown flag is set. The thread is a ``daemon=True`` thread, so
    it never blocks process exit. A failure opening ``app.db`` is logged and
    the heartbeat is simply skipped — the search server still serves
    requests; only the dashboard's "search" tile goes stale (web-redesign
    spec §5, Wave 6: heartbeats are best-effort).

    Args:
        settings: Application settings — only ``APP_DB_PATH`` is read here.
    """

    def _run() -> None:
        try:
            conn = connect_app_db(os.environ.get("APP_DB_PATH", "/data/app.db"))
            ensure_app_db_schema(conn)
        except Exception as exc:  # noqa: BLE001
            # rationale: best-effort heartbeat — if app.db cannot be opened
            # the search server still works; only the dashboard tile is lost.
            log.warning("api.heartbeat_disabled", error=str(exc))
            return
        heartbeat = Heartbeat(name="search", conn=conn)
        try:
            run_heartbeat_ticker(
                heartbeat,
                detail_fn=lambda: "serving search requests",
                interval_seconds=_SEARCH_HEARTBEAT_INTERVAL_SECONDS,
                should_stop=is_shutdown_requested,
            )
        finally:
            conn.close()

    thread = threading.Thread(target=_run, name="search-heartbeat", daemon=True)
    thread.start()
    log.info("api.heartbeat_started")


def create_app(
    settings: Settings,
    *,
    core: SearchCore | None = None,
    store_reader: StoreReader | None = None,
    app_db_path: str | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    Builds the search core from *settings* when *core*/*store_reader* are not
    supplied (production), migrates ``app.db``, detects first-run setup, and
    wires the account context onto the app. The ``app.db`` *path* — not a live
    connection — is what the app holds: each request opens its own connection
    through :func:`~search.deps.get_app_db`, because a ``sqlite3.Connection``
    cannot be safely shared across the threads FastAPI serves requests on.

    Args:
        settings: Application settings.
        core: An optional pre-built :class:`~search.core.SearchCore`.
        store_reader: An optional pre-built :class:`~store.reader.StoreReader`.
        app_db_path: An optional ``app.db`` path. Tests pass a ``tmp_path``
            file; production passes ``None`` and ``settings.APP_DB_PATH`` is
            used.

    Returns:
        A configured FastAPI application.
    """
    core, store_reader = _resolve_components(settings, core, store_reader)
    app_db_path = settings.APP_DB_PATH if app_db_path is None else app_db_path

    app = FastAPI(title="Paperless Semantic Search", docs_url=None, redoc_url=None)

    # Startup uses ONE short-lived connection: migrate app.db, then decide
    # whether first-run setup is needed. It is closed immediately — request
    # work opens its own connection per request (search.deps.get_app_db).
    setup_state = SetupState()
    startup_conn = open_app_db(app_db_path)
    try:
        if is_setup_needed(startup_conn):
            # No users yet: enter setup mode — generate a token and log it
            # prominently (spec §4.5).
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

    attach_app_state(
        app.state,
        AppState(app_db_path=app_db_path, setup_state=setup_state),
    )

    # Pre-populate the per-request core cache with the startup-built core so
    # the first request hits the cache and pays only a one-row SELECT — the
    # per-request accessor takes over from here, rebuilding only on a config
    # change (web-redesign §5, Wave 4).
    _seed_core_cache(app_db_path, core)

    # Mount /mcp and the /api routers BEFORE the SPA catch-all so they take
    # precedence over static serving.
    app.mount("/mcp", build_mcp_app(core, settings, app_db_path))
    app.include_router(build_account_router(store_reader))
    app.include_router(build_settings_router())
    app.include_router(build_api_key_router())
    app.include_router(build_document_router(settings))
    app.include_router(build_index_router(settings, store_reader))
    app.include_router(
        build_api_router(
            settings,
            _resolve_search_core,
            store_reader,
            require_reader=require_api_scope,
            require_member=require_api_scope_member,
            get_current_user=get_current_user,
        )
    )

    register_spa(app, _FRONTEND_DIST)
    _start_search_heartbeat(settings)
    return app


def _resolve_components(
    settings: Settings,
    core: SearchCore | None,
    store_reader: StoreReader | None,
) -> tuple[SearchCore, StoreReader]:
    """Return the core and store reader, building any not supplied by a caller.

    Tests inject pre-built stubs; production passes neither and gets the real
    component graph wired from *settings*.
    """
    if core is not None and store_reader is not None:
        return core, store_reader

    from common.embeddings import EmbeddingClient
    from search.core import SearchCore
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
        )
    return core, store_reader


# Process-local hot-reload cache for the search core: app.db path ->
# (config_version, core). _resolve_search_core rebuilds the config-derived
# component graph only when the configuration has changed (web-redesign §5,
# Wave 4); a steady-state request pays one cheap one-row SELECT.
_CORE_CACHE: dict[str, tuple[int, "SearchCore"]] = {}

# Serialises the rebuild path so two concurrent first-callers (or two callers
# landing on a fresh config_version) do not both build a core. The cache
# lookup itself stays lock-free; only the rebuild is gated.
_CORE_CACHE_LOCK = threading.Lock()


def _resolve_search_core(app_db_path: str) -> SearchCore:
    """Return the search core for the current configuration, rebuilt on change.

    Called per request. Reads ``config_version`` under a snapshot; when it is
    unchanged since the last call for this *app_db_path*, returns the cached
    core. When it has moved, rebuilds the core (and its :class:`Settings`,
    via :func:`common.config.current_settings`) from the new configuration so
    the next query uses the edited values — no restart.

    The shared process singletons that LLM calls go through —
    :func:`common.library_setup.setup_libraries` (the ``_openai_holder``) and
    :func:`common.concurrency.llm_limiter.init` (the concurrency limiter) —
    are re-initialised here whenever a new :class:`Settings` is built. The
    planner and synthesiser read the OpenAI client through ``_openai_holder``,
    so a saved ``OPENAI_API_KEY`` / ``LLM_PROVIDER`` / ``OLLAMA_BASE_URL`` /
    ``LLM_MAX_CONCURRENT`` change propagates to every LLM call on the very
    next request — the daemons do the same in their ``_reload_if_changed``
    hooks.

    Args:
        app_db_path: Filesystem path to ``app.db``. The search server passes
            ``AppState.app_db_path`` (the value resolved at app build time).

    Returns:
        The current :class:`SearchCore`.
    """
    from appdb import config as config_store  # noqa: PLC0415
    from appdb.connection import connect  # noqa: PLC0415
    from appdb.schema import ensure_schema  # noqa: PLC0415
    from common.config import current_settings  # noqa: PLC0415

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
        # were waiting. Re-read config_version too, so we never cache against
        # a version that has moved on since we measured it outside the lock.
        conn = connect(app_db_path)
        try:
            version = config_store.get_config_version(conn)
        finally:
            conn.close()
        cached = _CORE_CACHE.get(app_db_path)
        if cached is not None and cached[0] == version:
            return cached[1]

        # current_settings opens its own snapshot transaction; it returns a
        # Settings keyed at whatever version was current inside that
        # transaction. We then re-read config_version once more after the
        # build so the cache entry is keyed against the version of the data
        # the rebuilt core actually saw — if a write landed between
        # current_settings() and now, the cached pair (newer_version, core)
        # is stale on its face and a subsequent request will rebuild rather
        # than serve the stale core.
        settings = current_settings(app_db_path)
        setup_libraries(settings)
        llm_limiter.init(settings.LLM_MAX_CONCURRENT)
        core, _store_reader = _resolve_components(settings, None, None)
        conn = connect(app_db_path)
        try:
            cache_version = config_store.get_config_version(conn)
        finally:
            conn.close()
        _CORE_CACHE[app_db_path] = (cache_version, core)
        return core


def _reset_core_cache_for_test() -> None:
    """Clear the process-local search-core cache — for tests only."""
    _CORE_CACHE.clear()


def _seed_core_cache(app_db_path: str, core: SearchCore) -> None:
    """Prime the per-request core cache with the startup-built *core*.

    Reads the current ``config_version`` from *app_db_path* and stores the
    pair so the first request hits the cache and pays only a one-row
    ``SELECT`` — the per-request accessor rebuilds only on a later config
    change (web-redesign §5, Wave 4).
    """
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

    Runs the shared per-process bootstrap, then builds and serves the app.
    ``app.db`` is migrated inside :func:`create_app`. ``SEARCH_API_KEY`` is
    retired (Wave 3): programmatic access is by minted API keys only, so the
    legacy key is neither read nor required.

    uvicorn is run with ``proxy_headers=True`` so that, behind the documented
    nginx + Cloudflare deployment, ``request.url.scheme`` reflects the real
    edge scheme (HTTPS — so the session cookie gets its ``Secure`` flag) and
    ``request.client.host`` reflects the real client IP from
    ``X-Forwarded-For`` (so ``sessions.ip`` records the client, not the
    proxy). ``forwarded_allow_ips="*"`` trusts those headers from any peer:
    the search server's port is never exposed directly — only the reverse
    proxy reaches it — so every inbound connection is the trusted proxy.
    """
    from common.bootstrap import bootstrap_process

    settings = bootstrap_process()

    try:
        app = create_app(settings)
    except Exception:
        # rationale: outer-boundary catch (CODE_GUIDELINES §6.4) — a failure
        # here (e.g. an app.db written by newer code) must abort startup
        # loudly rather than serve a half-built app.
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
        forwarded_allow_ips="*",
    )
