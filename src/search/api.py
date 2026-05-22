"""FastAPI search server — HTTP API, account management, SPA, and MCP mount.

One uvicorn process serves:
- the account endpoints (setup, login/logout/me, user CRUD) — ``account_routes``
- the search endpoints (search, facets, stats, reconcile, healthz) — ``routes``
- ``/mcp``  — the MCP streamable-HTTP ASGI app
- ``/``     — the built React SPA, with a deep-link catch-all

This module is component wiring only: build the core, open ``app.db`` and run
its migrations, enter setup mode if there are no users, attach the per-app
account context, mount the routers and the SPA.

Security invariants (web-redesign §4; CODE_GUIDELINES §10):
- Browser auth is a server-side session behind an opaque, hashed cookie.
- ``Authorization: Bearer <SEARCH_API_KEY>`` keeps working as a legacy
  admin-equivalent through Waves 1-2.
- The index DB is never web-reachable — static serving is rooted only at the
  built frontend directory.

Allowed deps: fastapi, uvicorn, starlette, search (routes, account_routes,
    deps, appstate, setup, spa, appdb_setup, mcp_server, core), store
    (reader), appdb, common.config.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import uvicorn
from fastapi import FastAPI

from search.account_routes import build_account_router
from search.appdb_setup import open_app_db
from search.appstate import AppState, attach_app_state
from search.deps import require_role
from search.mcp_server import build_mcp_app
from search.routes import build_api_router
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


def create_app(
    settings: Settings,
    *,
    core: SearchCore | None = None,
    store_reader: StoreReader | None = None,
    app_db: sqlite3.Connection | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    Builds the search core from *settings* when *core*/*store_reader* are not
    supplied (production), opens and migrates ``app.db`` when *app_db* is not
    supplied, and wires the account context onto the app.

    Args:
        settings: Application settings.
        core: An optional pre-built :class:`~search.core.SearchCore`.
        store_reader: An optional pre-built :class:`~store.reader.StoreReader`.
        app_db: An optional pre-opened, migrated ``app.db`` connection. Tests
            inject a ``tmp_path`` connection; production passes ``None`` and
            gets one opened from ``settings.APP_DB_PATH``.

    Returns:
        A configured FastAPI application.
    """
    core, store_reader = _resolve_components(settings, core, store_reader)
    app_db = open_app_db(settings.APP_DB_PATH) if app_db is None else app_db

    app = FastAPI(
        title="Paperless Semantic Search", docs_url=None, redoc_url=None
    )

    # Build the first-run setup state: when app.db has no users the server is
    # in setup mode — generate a token and log it prominently (spec §4.5).
    setup_state = SetupState()
    if is_setup_needed(app_db):
        setup_state.token = generate_setup_token()
        log.warning(
            "search.setup_mode",
            message=(
                f"SETUP TOKEN: {setup_state.token} — open /setup to create "
                "the first admin account"
            ),
        )

    attach_app_state(
        app.state,
        AppState(
            app_db=app_db,
            setup_state=setup_state,
            legacy_api_key=settings.SEARCH_API_KEY,
        ),
    )

    # Mount /mcp and the /api routers BEFORE the SPA catch-all so they take
    # precedence over static serving.
    app.mount("/mcp", build_mcp_app(core, settings, app_db))
    app.include_router(build_account_router(store_reader))
    app.include_router(
        build_api_router(
            settings,
            core,
            store_reader,
            require_reader=require_role("readonly"),
            require_member=require_role("member"),
        )
    )

    register_spa(app, _FRONTEND_DIST)
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


def main() -> None:
    """Start the search server (entry point: ``paperless-search-server``).

    Runs the shared per-process bootstrap, then builds and serves the app.
    ``app.db`` is opened and migrated inside :func:`create_app`. The legacy
    ``SEARCH_API_KEY`` is now **optional**: with database-backed accounts a
    deployment can run with no legacy key at all, so an empty key is no
    longer fatal — it simply disables the legacy bearer path.
    """
    from common.bootstrap import bootstrap_process

    settings = bootstrap_process()

    if not settings.SEARCH_API_KEY.strip():
        # Not fatal any more — accounts are the primary auth. Just note it.
        log.info(
            "search.no_legacy_api_key",
            message=(
                "SEARCH_API_KEY is unset — the legacy Bearer path is "
                "disabled; sign in with a user account."
            ),
        )

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
    )
