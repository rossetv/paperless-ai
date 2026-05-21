"""FastAPI search server — HTTP API, static Web UI, and MCP mount (spec §7.1).

One uvicorn process serves:
- ``POST /api/auth/login`` — API-key exchange for a signed session cookie
- ``GET /api/healthz``     — liveness; 503 when the index is absent or corrupt
- ``POST /api/search``     — full agentic search pipeline
- ``GET /api/facets``      — taxonomy facets for the UI filter panel
- ``GET /api/stats``       — index statistics
- ``POST /api/reconcile``  — manual reconciliation trigger (spec §5.8)
- ``/mcp``                 — MCP streamable-HTTP ASGI app (spec §7.2)
- ``/``                    — the built React SPA (``web/dist``)

The six ``/api/*`` route handlers live in :mod:`search.routes`; this module is
component wiring only — build the core, build the auth dependency, create the
app, mount the MCP sub-app and the ``/api`` router, mount the SPA.

Security invariants (spec §9.2, ``CODE_GUIDELINES.md`` §10):
- ``SEARCH_API_KEY`` is mandatory; the server refuses to start without it.
- Every ``/api/*`` endpoint except ``/api/auth/login`` and ``/api/healthz``
  requires a valid Bearer token or a valid signed session cookie.
- The index DB is never web-reachable — ``StaticFiles`` is mounted **only** at
  the built frontend directory, never over ``/data`` or any path that contains
  the index file.

Allowed deps: fastapi, uvicorn, starlette, search (routes, auth, core,
    mcp_server), store (reader), common.config.
Forbidden: sqlite3, direct LLM/HTTP calls, imports from indexer/.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from search.auth import (
    SESSION_COOKIE_NAME,
    extract_bearer,
    is_request_authenticated,
)
from search.mcp_server import build_mcp_app
from search.routes import build_api_router

if TYPE_CHECKING:
    from collections.abc import Callable

    from common.config import Settings
    from search.core import SearchCore
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Path to the built frontend.
#
# Resolution order (first non-empty value wins):
# 1. ``FRONTEND_DIST`` environment variable — set to ``/app/web/dist`` by the
#    Dockerfile so the installed-package path works correctly inside the
#    container regardless of where pip placed ``api.py``.
# 2. The path relative to this file's *repository* root — works for direct
#    source-tree execution (``python -m search.api``) and for local dev where
#    the package is installed with ``pip install -e .``.
#
# The path is resolved at import time; a missing directory silently skips the
# static mount rather than crashing the server (unit tests, pre-build).
_env_frontend = os.environ.get("FRONTEND_DIST", "").strip()
if _env_frontend:
    _FRONTEND_DIST = Path(_env_frontend)
else:
    _REPO_ROOT = Path(__file__).parent.parent.parent
    _FRONTEND_DIST = _REPO_ROOT / "web" / "dist"


# ---------------------------------------------------------------------------
# Authentication dependency
# ---------------------------------------------------------------------------


def _make_require_auth(settings: Settings) -> Callable[[Request], None]:
    """Return a FastAPI dependency that enforces authentication.

    Extracts the Bearer token from the ``Authorization`` header and the session
    cookie from the request, then delegates to
    :func:`~search.auth.is_request_authenticated`.  Raises HTTP 401 on failure.

    The key is **never logged** (``CODE_GUIDELINES.md`` §7.4, §10.3).

    Args:
        settings: Application settings carrying ``SEARCH_API_KEY``.
    """

    def require_auth(request: Request) -> None:
        """FastAPI dependency; raises 401 if the request is not authenticated."""
        bearer = extract_bearer(request.headers.get("authorization"))
        cookie = request.cookies.get(SESSION_COOKIE_NAME)

        if not is_request_authenticated(
            bearer=bearer, cookie=cookie, settings=settings
        ):
            log.warning(
                "api.auth_rejected",
                has_auth_header=bearer is not None,
                has_cookie=cookie is not None,
            )
            raise HTTPException(status_code=401, detail="Unauthorised")

    return require_auth


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    settings: Settings,
    *,
    core: SearchCore | None = None,
    store_reader: StoreReader | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    Constructs the search core from ``settings`` when *core* or *store_reader*
    are not provided (i.e. in production).  Both parameters exist so that unit
    and integration tests can inject pre-built stubs without touching the
    environment or the filesystem.

    Args:
        settings: Application settings.
        core: An optional pre-built :class:`~search.core.SearchCore`.  When
            ``None``, the core is constructed from *settings*.
        store_reader: An optional pre-built :class:`~store.reader.StoreReader`.
            When ``None``, one is constructed from *settings*.

    Returns:
        A configured FastAPI application.
    """
    core, store_reader = _resolve_components(settings, core, store_reader)

    app = FastAPI(title="Paperless Semantic Search", docs_url=None, redoc_url=None)

    # Mount the MCP ASGI app and the /api router BEFORE the SPA catch-all so
    # /mcp and /api/* take precedence over the static mount (spec §7.2).
    app.mount("/mcp", build_mcp_app(core, settings))
    app.include_router(
        build_api_router(
            settings, core, store_reader, _make_require_auth(settings)
        )
    )

    _mount_frontend(app)
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


def _mount_frontend(app: FastAPI) -> None:
    """Mount the built React SPA at ``/`` if its directory exists.

    The static mount must come AFTER the ``/api/*`` and ``/mcp`` routes so
    they take precedence.  A missing ``web/dist`` directory (unit tests,
    pre-build) silently skips the mount rather than crashing the server.

    Security: mounted ONLY at ``web/dist`` — never over ``/data`` or the index
    directory, so the index DB is never web-reachable.
    """
    if _FRONTEND_DIST.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(_FRONTEND_DIST), html=True),
            name="frontend",
        )
        log.info("api.frontend_mounted", path=str(_FRONTEND_DIST))
    else:
        log.info(
            "api.frontend_not_mounted",
            path=str(_FRONTEND_DIST),
            reason="web/dist directory not found; skipping static mount",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the search server (entry point: ``paperless-search-server``).

    PREFLIGHT — fail closed (spec §9.2, ``CODE_GUIDELINES.md`` §10.1):
    An empty ``SEARCH_API_KEY`` is a fatal error; the server refuses to start.
    Serving the operator's personal document archive without authentication
    is a data-breach one misconfiguration away (spec §9.2).
    """
    from common.bootstrap import bootstrap_process

    # Run the per-process startup shared with the daemons: Settings, logging,
    # the library singletons (the OpenAI client), signal handlers, and the LLM
    # concurrency limiter.  Centralised in common.bootstrap so the search
    # server cannot drift from the daemons — omitting the limiter step here is
    # what previously 500ed every query (see bootstrap_process).
    settings = bootstrap_process()

    # Fail closed: the API key is mandatory (spec §10.1, §9.2).
    # Strip whitespace before checking — a key of "   " is effectively absent
    # and must not allow the server to start with a near-empty credential.
    if not settings.SEARCH_API_KEY.strip():
        logging.critical(
            "SEARCH_API_KEY is not set or is whitespace-only — the search "
            "server refuses to start without a real API key.  Set "
            "SEARCH_API_KEY in the environment."
        )
        sys.exit(1)

    app = create_app(settings)

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
