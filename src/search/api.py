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

Security invariants (spec §9.2, ``CODE_GUIDELINES.md`` §10):
- ``SEARCH_API_KEY`` is mandatory; the server refuses to start without it.
- Every ``/api/*`` endpoint except ``/api/auth/login`` and ``/api/healthz``
  requires a valid Bearer token or a valid signed session cookie.
- The index DB is never web-reachable — ``StaticFiles`` is mounted **only** at
  the built frontend directory, never over ``/data`` or any path that contains
  the index file.

Allowed deps: fastapi, uvicorn, starlette, search (wire, auth, core,
    mcp_server), store (reader), common.config.
Forbidden: sqlite3, direct LLM/HTTP calls, imports from indexer/.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

from search.auth import (
    SESSION_COOKIE_NAME,
    cookie_attributes,
    extract_bearer,
    is_request_authenticated,
    verify_api_key,
)
from search.mcp_server import build_mcp_app
from search.wire import (
    LoginRequest,
    SearchRequest,
    to_facets_response,
    to_search_response,
    to_stats_response,
)
from store.migrations import StoreError

if TYPE_CHECKING:
    from common.config import Settings
    from search.core import SearchCore
    from store.reader import StoreReader

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# The reconciliation sentinel file name (spec §5.8).  Written alongside the
# index DB; picked up by the indexer's polling loop.
_RECONCILE_SENTINEL_NAME = "reconcile.request"

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
import os as _os  # noqa: E402

_env_frontend = _os.environ.get("FRONTEND_DIST", "").strip()
if _env_frontend:
    _FRONTEND_DIST = Path(_env_frontend)
else:
    _REPO_ROOT = Path(__file__).parent.parent.parent
    _FRONTEND_DIST = _REPO_ROOT / "web" / "dist"


# ---------------------------------------------------------------------------
# Authentication dependency
# ---------------------------------------------------------------------------


def _make_require_auth(settings: Settings):  # type: ignore[return]
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
            ``None``, the core is constructed from *settings* using the wiring
            described in the spec.
        store_reader: An optional pre-built
            :class:`~store.reader.StoreReader`.  When ``None``, one is
            constructed from *settings*.

    Returns:
        A configured FastAPI application.
    """
    # Build the core and store reader if not injected (production path).
    if store_reader is None or core is None:
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
            planner = QueryPlanner(settings)
            retriever = Retriever(settings, store_reader, embedding_client)
            synthesizer = Synthesizer(settings)
            core = SearchCore(settings, store_reader, planner, retriever, synthesizer)

    # Per-request concurrency semaphore for /api/search (spec §7.4).
    # Created lazily on the first request so it is always bound to the
    # event loop that is actually serving requests, not the one (if any) that
    # happened to be running at app-factory time.  The double-check inside the
    # lock is not needed here because we rely on asyncio's single-threaded
    # contract: only one coroutine accesses _search_semaphore_holder at a time.
    _search_semaphore_holder: list[asyncio.Semaphore] = []

    def _get_search_semaphore() -> asyncio.Semaphore:
        if not _search_semaphore_holder:
            _search_semaphore_holder.append(
                asyncio.Semaphore(settings.SEARCH_MAX_CONCURRENT)
            )
        return _search_semaphore_holder[0]

    # The single auth dependency applied to all protected endpoints.
    _auth_dep = _make_require_auth(settings)

    app = FastAPI(title="Paperless Semantic Search", docs_url=None, redoc_url=None)

    # ------------------------------------------------------------------
    # Mount MCP ASGI app BEFORE any catch-all routes (spec §7.2).
    # /api/* and /mcp take precedence over the SPA static mount.
    # ------------------------------------------------------------------
    mcp_app = build_mcp_app(core, settings)
    app.mount("/mcp", mcp_app)

    # ------------------------------------------------------------------
    # POST /api/auth/login — unauthenticated (this is how you log in)
    # ------------------------------------------------------------------

    @app.post("/api/auth/login")
    async def login(body: LoginRequest, response: Response) -> dict[str, str]:
        """Exchange the API key for a signed session cookie (spec §7.3).

        Returns:
            A JSON body with ``status: "ok"`` on success.

        Raises:
            HTTPException 401: When the supplied key does not match.
        """
        if not verify_api_key(body.api_key, settings.SEARCH_API_KEY):
            # The wrong key is never logged — only that an attempt was made.
            log.warning("api.login_rejected")
            raise HTTPException(status_code=401, detail="Invalid API key")

        token = _issue_token(settings)
        _set_session_cookie(response, token, settings)
        log.info("api.login_ok")
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # GET /api/healthz — unauthenticated (spec §3.2, §4.7)
    # ------------------------------------------------------------------

    @app.get("/api/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness check; surfaces index state to the Docker healthcheck.

        Three outcomes (spec §4.7):

        - **200** ``{"status": "ok"}`` — the index has a schema, has been
          reconciled at least once, and ``quick_check`` passes.
        - **503** ``{"status": "index-not-ready"}`` — the DB file is absent,
          OR exists but has no schema (``meta``/``documents`` tables missing),
          OR has a schema but has never been reconciled
          (``last_reconcile_at`` is ``None``).  All of these mean the
          indexer has not finished building the index yet.
        - **503** ``{"status": "index-corrupt"}`` — the DB exists with a
          schema and a reconcile timestamp, but ``quick_check`` reports
          corruption.

        The handler never raises: any unexpected error becomes a clean 503.

        Note on the empty-file edge case: ``sqlite3.connect`` creates an
        empty DB when the path does not exist and the directory is writable,
        so a missing-table ``OperationalError`` from ``get_stats()`` is the
        canonical signal for "file present but not yet initialised by the
        indexer".  We treat that as ``index-not-ready``, not corrupt.
        """
        db_path = Path(settings.INDEX_DB_PATH)
        if not db_path.exists():
            # The indexer has not created the DB yet (spec §3.2).
            log.info("api.healthz_not_ready", reason="db_absent")
            return Response(  # type: ignore[return-value]
                content='{"status":"index-not-ready"}',
                status_code=503,
                media_type="application/json",
            )

        # Try to read index statistics.  An OperationalError here means the
        # schema has not been created yet (e.g. sqlite3.connect auto-created
        # an empty file before the indexer ran StoreWriter.ensure_schema).
        # Any other unexpected error is also treated as not-ready to avoid
        # leaking internal details.
        try:
            stats = store_reader.get_stats()
        except StoreError as exc:
            # StoreError wraps sqlite3.Error; unwrap to check the root cause.
            cause = exc.__cause__
            if isinstance(cause, sqlite3.OperationalError) and "no such table" in str(
                cause
            ).lower():
                log.info("api.healthz_not_ready", reason="schema_missing")
            else:
                log.info("api.healthz_not_ready", reason="stats_error", error=str(exc))
            return Response(  # type: ignore[return-value]
                content='{"status":"index-not-ready"}',
                status_code=503,
                media_type="application/json",
            )
        except Exception as exc:
            log.warning("api.healthz_not_ready", reason="unexpected_error", error=str(exc))
            return Response(  # type: ignore[return-value]
                content='{"status":"index-not-ready"}',
                status_code=503,
                media_type="application/json",
            )

        # Schema exists; check whether the indexer has ever completed a
        # reconciliation cycle.  A None last_reconcile_at means the schema
        # was written but the first reconciliation has not finished.
        if stats.last_reconcile_at is None:
            log.info("api.healthz_not_ready", reason="never_reconciled")
            return Response(  # type: ignore[return-value]
                content='{"status":"index-not-ready"}',
                status_code=503,
                media_type="application/json",
            )

        # Schema is present and at least one reconciliation has completed.
        # Now verify physical integrity.
        try:
            ok = store_reader.quick_check()
        except StoreError:
            ok = False

        if not ok:
            log.warning("api.healthz_corrupt")
            return Response(  # type: ignore[return-value]
                content='{"status":"index-corrupt"}',
                status_code=503,
                media_type="application/json",
            )

        return {"status": "ok"}

    # ------------------------------------------------------------------
    # POST /api/search — authenticated, concurrency-bounded (spec §7.4)
    # ------------------------------------------------------------------

    @app.post("/api/search", dependencies=[Depends(_auth_dep)])
    async def search(body: SearchRequest) -> dict:  # type: ignore[return]
        """Run the full agentic search pipeline and return a SearchResponse.

        Bounded by ``SEARCH_MAX_CONCURRENT`` to limit simultaneous LLM spend.
        """
        from store.reader import SearchFilters

        ui_filters: SearchFilters | None = None
        if body.filters is not None:
            ui_filters = SearchFilters(
                date_from=body.filters.date_from,
                date_to=body.filters.date_to,
                correspondent_id=body.filters.correspondent_id,
                document_type_id=body.filters.document_type_id,
                tag_ids=tuple(body.filters.tag_ids),
            )

        # rationale: asyncio.Semaphore caps concurrent LLM calls; the actual
        # SearchCore.answer call is CPU-light wiring with blocking I/O (LLM
        # HTTP + SQLite); run_in_executor keeps the event loop unblocked.
        # The semaphore is fetched lazily so it is always bound to the
        # current event loop (see _get_search_semaphore above).
        async with _get_search_semaphore():
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: core.answer(query=body.query, ui_filters=ui_filters)
            )

        return to_search_response(result).model_dump()

    # ------------------------------------------------------------------
    # GET /api/facets — authenticated
    # ------------------------------------------------------------------

    @app.get("/api/facets", dependencies=[Depends(_auth_dep)])
    async def facets() -> dict:  # type: ignore[return]
        """Return taxonomy facets for the search UI filter panel."""
        loop = asyncio.get_event_loop()
        facet_set = await loop.run_in_executor(None, store_reader.list_facets)
        return to_facets_response(facet_set).model_dump()

    # ------------------------------------------------------------------
    # GET /api/stats — authenticated
    # ------------------------------------------------------------------

    @app.get("/api/stats", dependencies=[Depends(_auth_dep)])
    async def stats() -> dict:  # type: ignore[return]
        """Return summary statistics for the search index."""
        loop = asyncio.get_event_loop()
        index_stats = await loop.run_in_executor(None, store_reader.get_stats)
        return to_stats_response(index_stats).model_dump()

    # ------------------------------------------------------------------
    # POST /api/reconcile — authenticated, 202 Accepted (spec §5.8)
    # ------------------------------------------------------------------

    @app.post("/api/reconcile", dependencies=[Depends(_auth_dep)])
    async def reconcile() -> Response:
        """Touch the reconciliation sentinel file and return 202 Accepted.

        The indexer's polling loop detects the sentinel on its next slice and
        starts an immediate reconciliation cycle (spec §5.8).

        Security: writes ONLY the sentinel — never the index DB.
        """
        db_dir = Path(settings.INDEX_DB_PATH).parent
        sentinel = db_dir / _RECONCILE_SENTINEL_NAME
        sentinel.touch()
        log.info("api.reconcile_triggered", sentinel=str(sentinel))
        return Response(status_code=202)

    # ------------------------------------------------------------------
    # Mount the built frontend (SPA) — must come AFTER all /api/* routes
    # so the API routes take precedence.
    # SECURITY: mounted ONLY at web/dist — never over /data or the index dir.
    # ------------------------------------------------------------------
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

    return app


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _issue_token(settings: Settings) -> str:
    """Issue a signed session token using the current wall clock."""
    from search.auth import issue_session_token

    return issue_session_token(
        settings.SEARCH_API_KEY,
        ttl_seconds=settings.SEARCH_SESSION_TTL,
        now=time.time(),
    )


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """Set the signed session cookie on *response* with all required security flags.

    Delegates all cookie attributes to :func:`~search.auth.cookie_attributes`
    so that function is the single source of truth for HttpOnly, Secure,
    SameSite, Path, and Max-Age.  Explicit kwargs (rather than a ``**splat``)
    keep mypy happy against ``Response.set_cookie``'s typed signature.

    Args:
        response: The FastAPI response object to set the cookie on.
        token: The signed session token string.
        settings: Application settings; passed to ``cookie_attributes`` so it
            can read ``SEARCH_SESSION_TTL`` for ``max_age``.
    """
    attrs = cookie_attributes(settings)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=attrs["max_age"],  # type: ignore[arg-type]
        path=attrs["path"],  # type: ignore[arg-type]
        httponly=attrs["httponly"],  # type: ignore[arg-type]
        secure=attrs["secure"],  # type: ignore[arg-type]
        samesite=attrs["samesite"],  # type: ignore[arg-type]
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
    from common.config import Settings
    from common.library_setup import setup_libraries
    from common.logging_config import configure_logging
    from common.shutdown import register_signal_handlers

    settings = Settings()
    configure_logging(settings)
    setup_libraries(settings)
    register_signal_handlers()

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

    # Build the production component graph.
    from common.embeddings import EmbeddingClient
    from search.core import SearchCore
    from search.planner import QueryPlanner
    from search.retriever import Retriever
    from search.synthesizer import Synthesizer
    from store.reader import StoreReader

    store_reader = StoreReader(settings)
    embedding_client = EmbeddingClient(settings)
    planner = QueryPlanner(settings)
    retriever = Retriever(settings, store_reader, embedding_client)
    synthesizer = Synthesizer(settings)
    core = SearchCore(settings, store_reader, planner, retriever, synthesizer)

    app = create_app(settings, core=core, store_reader=store_reader)

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
