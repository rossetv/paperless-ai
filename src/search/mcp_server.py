"""MCP endpoint for the search server (spec §7.2/§7.3).

``build_mcp_app`` constructs a FastMCP server with the streamable-HTTP transport
and wraps it in a bearer-token authentication middleware.  The returned ASGI
application is mounted at ``/mcp`` by the HTTP server; this module has no
dependency on ``search/api.py``.

Five tools are exposed; only ``deep_search`` is billed:

- ``semantic_search(query, filters?)`` — calls ``core.retrieve()``.  Pure
  hybrid (vector + FTS) retrieval: ranked source documents, no synthesised
  answer, and **zero chat LLM calls**.  The PREFERRED tool.
- ``keyword_search(query?, filters?, limit?, offset?)`` — calls
  ``core.keyword_search()``.  Exact FTS keyword (or filter-only browse) →
  ranked document list.  Zero LLM, local index only.
- ``fetch_documents(document_ids)`` — calls ``core.fetch_documents()``.  Full
  OCR text (capped) for up to 5 documents, fetched live from Paperless via a
  per-request client.  Zero LLM.
- ``list_filters()`` — calls ``core.list_filters()``.  Every correspondent /
  document type / tag (with counts) + the date range, from the local index.
  Zero LLM.
- ``deep_search(question, filters?)`` — calls ``core.answer()``.  Runs the
  full server-side agentic pipeline and returns a synthesised answer.  Every
  call spends the archive owner's LLM API budget, so it is the last resort
  (spec §7.2).

The two query-shaped tools share one body helper (:func:`_run_search_tool`):
normalise the query at the boundary (trim, reject empty/whitespace-only,
enforce the maximum length — §10.4/§10.6), convert the optional filters, invoke
the core method, serialise the result, and turn any failure into a sanitised
tool error.  All five go through :func:`_run_tool`, which exempts the four
zero-LLM tools from the spend quota (``bills_llm=False``).

Authentication (web-redesign §5):
  Every request must carry either a browser ``search_session`` cookie or an
  ``Authorization: Bearer sk-pls-...`` API key whose scopes include ``mcp``.
  The middleware calls :func:`search.sessions.resolve_session` and
  :func:`search.api_keys.resolve_api_key` and returns HTTP 401 without
  reaching the MCP handler if neither credential is valid. The legacy
  ``SEARCH_API_KEY`` was retired in Wave 3. No secret is ever logged.

Allowed deps: search (core, api_keys, auth, sessions, models, sources, wire,
    identity, offload, spend_quota), store (SearchFilters), common (paperless,
    config), appdb (connection), mcp SDK, starlette. The ``app.db`` path is
    injected by the app factory; this module owns no SQL and opens a fresh
    connection per request, mirroring ``search.deps.get_app_db``.
Forbidden: FastAPI (api.py), direct LLM calls. ``fetch_documents`` does proxy
    to Paperless over HTTP, but only through an injected per-request
    ``PaperlessClient`` run off the loop — mirroring ``search.document_routes``.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from appdb.connection import connect
from common.paperless import PaperlessClient
from search.api_keys import SCOPE_MCP, resolve_api_key
from search.auth import SESSION_COOKIE_NAME, extract_bearer
from search.deps import refresh_last_seen
from search.identity import mcp_asker, resolve_asker
from search.models import SearchResult
from search.offload import LazySemaphore, run_blocking
from search.sessions import resolve_session
from search.sources import _paperless_url
from search.spend_quota import (
    QuotaExceededError,
    check_quota,
    mcp_api_key_id,
    record_usage,
)
from search.wire import FilterRequest, normalise_query, to_search_filters
from store import SearchFilters

if TYPE_CHECKING:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    from common.config import Settings
    from search.core import SearchCore


def _default_paperless_factory(settings: Settings) -> PaperlessClient:
    """Build a real :class:`~common.paperless.PaperlessClient` from *settings*.

    The production factory for ``fetch_documents``. Mirrors
    ``search.document_routes._default_paperless_factory`` (kept local so this
    module does not depend on a sibling route package). Tests pass their own
    factory returning a stub, so the tool never makes a real Paperless call.
    """
    return PaperlessClient(settings)


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# ASGI bearer-token middleware
# ---------------------------------------------------------------------------


class _BearerAuthMiddleware:
    """ASGI middleware that enforces session-cookie or API-key authentication.

    Extracts the ``Authorization: Bearer <token>`` header and the session
    cookie, then authorises a request that carries EITHER a browser session
    cookie that resolves to an active user (a human, not scope-limited) OR an
    API key that resolves AND whose scope set includes ``mcp``.  An
    unauthenticated request is rejected with HTTP 401 before the inner ASGI
    app is called.

    A successful cookie auth also refreshes ``last_seen_at`` (via
    :func:`~search.deps.refresh_last_seen`) so MCP-only users do not have a
    frozen last-seen timestamp.

    No secret is **ever logged** — a failed check records only whether a
    header or cookie was present, never its value (CODE_GUIDELINES §7.4).

    Args:
        app: The inner ASGI application to protect.
        app_db_path: The filesystem path to ``app.db``. A fresh connection is
            opened per request to resolve the cookie or the API key — an
            ``app.db`` connection is never shared across requests.
    """

    def __init__(self, app: ASGIApp, app_db_path: str) -> None:
        self._app = app
        self._app_db_path = app_db_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        request = Request(scope)
        bearer = extract_bearer(request.headers.get("authorization"))
        cookie = request.cookies.get(SESSION_COOKIE_NAME)

        # _resolve_caller resolves the credential, runs blocking SQLite, and
        # returns (authenticated, display_name, api_key_id). Offloaded so MCP
        # auth never blocks the event loop per request (raw ASGI, no FastAPI
        # auto-offload).
        auth_result = await run_blocking(lambda: self._resolve_caller(bearer, cookie))

        if not auth_result[0]:
            log.warning(
                "mcp.auth_rejected",
                has_auth_header=bearer is not None,
                has_cookie=cookie is not None,
            )
            response = Response(
                content=json.dumps({"error": "Unauthorised"}),
                status_code=401,
                media_type="application/json",
            )
            await response(scope, receive, send)
            return

        # Set the caller's display name AND api-key id on the contextvars so the
        # tool handlers downstream in the same async context can read them (the
        # asker for identity-aware prompts, the key id for the spend quota). Both
        # are reset in a finally so the contextvars are restored even if the
        # inner app raises — prevents state leaking to the next request sharing
        # this async context. api_key_id is ``None`` for a cookie caller, which
        # the quota correctly treats as "not limited".
        display_name = auth_result[1]
        asker_token = mcp_asker.set(display_name)
        key_id_token = mcp_api_key_id.set(auth_result[2])
        try:
            await self._app(scope, receive, send)
        finally:
            mcp_asker.reset(asker_token)
            mcp_api_key_id.reset(key_id_token)

    def _resolve_caller(
        self, bearer: str | None, cookie: str | None
    ) -> tuple[bool, str | None, int | None]:
        """Authenticate the request; return display name and API-key id.

        Authenticated when EITHER a browser ``search_session`` cookie resolves
        to an active user (a human, not scope-limited) OR an API key resolves
        AND that key carries the ``mcp`` scope. A key without ``mcp`` — e.g. an
        API-only key — cannot reach ``/mcp`` (web-redesign §5). The ``app.db``
        lookup uses a fresh per-request connection, closed before returning.

        Args:
            bearer: The extracted ``Authorization: Bearer`` token, or ``None``.
            cookie: The raw ``search_session`` cookie value, or ``None``.

        Returns:
            An ``(authenticated, display_name, api_key_id)`` triple. When
            unauthenticated, ``(False, None, None)`` is returned. The display
            name is the raw (unsanitised) value from the database — sanitisation
            happens in :func:`~search.identity.resolve_asker` at call time. The
            ``api_key_id`` is the matched key's id for an API-key caller, or
            ``None`` for a cookie caller (whom the spend quota never limits).
        """
        app_db = connect(self._app_db_path)
        try:
            user = resolve_session(app_db, cookie)
            if user is not None:
                # Refresh last_seen_at so MCP-only users do not have a frozen
                # timestamp — mirrors what search.deps.resolve_caller does for
                # the REST surface (CODE_GUIDELINES §10).
                refresh_last_seen(app_db, cookie)
                return True, user.display_name, None
            resolved = resolve_api_key(app_db, bearer)
            if resolved is not None and SCOPE_MCP in resolved.scopes:
                return True, resolved.owner_display_name, resolved.api_key_id
            return False, None, None
        finally:
            app_db.close()


# ---------------------------------------------------------------------------
# Shared tool body
# ---------------------------------------------------------------------------


def _serialise_result(result: SearchResult) -> str:
    """Serialise a SearchResult to a JSON string for MCP tool output.

    Uses :func:`dataclasses.asdict` to convert the frozen-dataclass tree to a
    plain dict, then serialises to JSON.  Tuples become lists in the output,
    which is fine for a wire format consumed by JSON clients.

    The verbose per-phase reasoning ``trace`` is dropped before serialising: it
    is a SPA-only affordance (the live search view) and carries the relevance
    judge's per-document rationales.  MCP/agent callers get the curated answer,
    sources, plan, and the lightweight ``cost`` summary, but not the heavy
    phase-by-phase trace — keeping the tool contract lean and intentional rather
    than leaking the SPA's trace surface.
    """
    payload = dataclasses.asdict(result)
    stats = payload.get("stats")
    if isinstance(stats, dict):
        stats.pop("trace", None)
    return json.dumps(payload)


def _total_tokens(serialised_result: str) -> int:
    """Read the whole-query total token count from a serialised tool result.

    The token total rides on ``stats.cost.tokens.total`` of the JSON
    :func:`_serialise_result` produces (the cost summary is retained — only the
    verbose trace is dropped). This reads it back for the spend-quota record.

    Defensive: any shape mismatch (a missing key, a non-numeric value, a future
    schema change) returns ``0`` rather than raising — the usage record is
    best-effort, so a parse failure must not break the tool response. Returns
    ``0`` on anything it cannot read as a non-negative integer total.

    Args:
        serialised_result: The JSON string a tool returns.

    Returns:
        The whole-query total token count, or ``0`` when it cannot be read.
    """
    try:
        payload = json.loads(serialised_result)
        total = payload["stats"]["cost"]["tokens"]["total"]
    except (ValueError, TypeError, KeyError):
        return 0
    return total if isinstance(total, int) and total >= 0 else 0


def _to_search_filters(raw: dict[str, Any] | None) -> SearchFilters | None:
    """Convert an optional raw filters dict to a :class:`SearchFilters`.

    The MCP boundary receives filters as an untyped dict.  This validates it
    through the :class:`~search.wire.FilterRequest` Pydantic model — the MCP
    server is an HTTP-shaped boundary, so Pydantic validation here is the
    documented pattern (CODE_GUIDELINES §5.6, §10.4) — then delegates to the
    one shared :func:`~search.wire.to_search_filters` converter.  Unknown keys
    are ignored; ``None`` or an empty dict means no filters.

    Args:
        raw: The raw filters dict from the tool call, or ``None``.

    Returns:
        A :class:`SearchFilters` instance, or ``None`` when no filters apply.
    """
    if not raw:
        return None
    return to_search_filters(FilterRequest.model_validate(raw))


def _run_search_tool(
    *,
    query: str,
    filters: dict[str, Any] | None,
    core_call: Callable[[str, SearchFilters | None, str | None], SearchResult],
    error_event: str,
    asker: str | None = None,
) -> str:
    """Run one search-tool body: validate, convert, invoke core, serialise.

    The shared body of both MCP tools.  It normalises *query* at the boundary
    via :func:`~search.wire.normalise_query` (trim, reject empty/whitespace-only,
    enforce the maximum length — §10.4/§10.6), converts the optional *filters*,
    invokes *core_call*, and serialises the result.  Any failure from the core
    is logged with its full traceback server-side and surfaced to the MCP
    client as a sanitised :class:`ValueError` carrying no internal detail.

    Args:
        query: The user's query or question.
        filters: The optional raw filters dict from the tool call.
        core_call: The :class:`~search.core.SearchCore` method to invoke —
            ``retrieve`` for ``semantic_search``, ``answer`` for
            ``deep_search``.
        error_event: The structured-log event name for a failure.
        asker: Optional sanitised display name of the requesting user,
            forwarded to the core so first-person references resolve correctly.

    Returns:
        The serialised :class:`~search.models.SearchResult` as a JSON string.

    Raises:
        ValueError: When *query* is empty/whitespace-only or exceeds
            :data:`~search.wire.MAX_QUERY_LENGTH`, or — sanitised — when the
            core call fails.
    """
    # Validate (and trim) the query at the boundary BEFORE the try/except so an
    # empty/whitespace-only or over-length query surfaces its own clear message
    # to the client, not the sanitised "search failed" fallback. The pipeline
    # only ever sees the normalised query (HTTP-04/HTTP-07).
    query = normalise_query(query)

    # rationale: outer-boundary catch (CODE_GUIDELINES §6.4) — this is the MCP
    # protocol boundary.  Raw exception strings from the core (which can carry
    # filesystem paths or internal state) must never reach the MCP client; the
    # full traceback is logged server-side instead.
    try:
        ui_filters = _to_search_filters(filters)
        result = core_call(query, ui_filters, asker)
        return _serialise_result(result)
    except Exception:
        log.exception(error_event)
        # from None: the original may carry filesystem paths or internal state
        # (CODE_GUIDELINES §6.3, §10) — the chain is severed deliberately, and
        # the full traceback is in the server log above.
        raise ValueError("search failed — see server logs") from None


# ---------------------------------------------------------------------------
# MCP app builder
# ---------------------------------------------------------------------------


class _McpApp:
    """Thin wrapper that exposes both the ASGI app and the FastMCP instance.

    The ASGI ``__call__`` delegates to the bearer-auth-wrapped Starlette app
    so the returned object is a valid ASGI application.  The ``_fastmcp``
    attribute gives tests access to the FastMCP instance for in-memory
    transport tests via ``create_connected_server_and_client_session``.

    Args:
        fastmcp: The configured FastMCP server.
        app_db_path: The filesystem path to ``app.db`` for session-cookie auth.
    """

    def __init__(
        self,
        fastmcp: FastMCP,
        app_db_path: str,
    ) -> None:
        self._fastmcp = fastmcp
        starlette_app = fastmcp.streamable_http_app()
        self._asgi_app: ASGIApp = _BearerAuthMiddleware(starlette_app, app_db_path)

    @property
    def session_manager(self) -> StreamableHTTPSessionManager:
        """The streamable-HTTP session manager, for the mounting app's lifespan.

        FastMCP wires this manager's task group via the lifespan of the app
        ``streamable_http_app()`` returns — but an ASGI sub-app attached by a
        Route (or app.mount) never has its own lifespan run by the parent, so
        that task group would stay uninitialised and every request would fail
        with "Task group is not initialized". The app factory
        (``search.api.create_app``) therefore
        runs ``session_manager.run()`` from the FastAPI app's own lifespan;
        this property exposes the manager for it. Available because
        ``streamable_http_app()`` (which creates it lazily) was called in
        ``__init__``.
        """
        return self._fastmcp.session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._asgi_app(scope, receive, send)


def _register_search_tools(
    mcp: FastMCP,
    resolve_core: Callable[[str], SearchCore],
    app_db_path: str,
    search_semaphore: LazySemaphore,
    paperless_factory: Callable[[Settings], PaperlessClient],
) -> None:
    """Register the MCP tools on *mcp*, every one resolving the live core.

    Each tool is a thin closure over :func:`_run_tool`. The two LLM-path tools
    go through :func:`_dispatch` and :func:`_run_search_tool`:
    ``semantic_search`` calls ``core.retrieve`` (pure RAG, sources only),
    ``deep_search`` calls ``core.answer`` (synthesised answer — the only billed
    tool). The three zero-LLM tools (``keyword_search``, ``fetch_documents``,
    ``list_filters``) call :func:`_run_tool` directly with ``bills_llm=False``,
    so they skip the spend quota. The core is resolved per call through
    *resolve_core* — mirroring the HTTP ``/api/search`` handler — so a saved
    configuration change (answer model, ``SEARCH_MAX_CONCURRENT``,
    ``OPENAI_API_KEY``, ``SEARCH_IDENTITY_AWARE``, ...) hot-loads for MCP callers
    on the very next call, with no restart.

    Args:
        mcp: The FastMCP server to register the tools on.
        resolve_core: Returns the live :class:`SearchCore` for the request's
            ``app.db`` path. Called per tool dispatch so MCP gets the same
            per-request hot-reload as the HTTP surface; it owns its own caching,
            so a steady-state call pays one cheap one-row ``SELECT``.
        app_db_path: The ``app.db`` path forwarded to *resolve_core* each call.
        search_semaphore: The concurrency bound, shared with the HTTP
            ``/api/search`` surface so ``SEARCH_MAX_CONCURRENT`` is one ceiling
            across both, not 2N. It binds lazily to the serving event loop.
    """

    async def _run_tool(
        build_output: Callable[[SearchCore], str],
        *,
        bills_llm: bool,
    ) -> str:
        """Run any tool body off the loop, under the shared concurrency bound.

        The single dispatch scaffold for every MCP tool. It resolves the live
        core per call via *resolve_core* (blocking SQLite, so off the loop), so a
        hot-reloaded answer model / API key / ``SEARCH_MAX_CONCURRENT`` /
        ``SEARCH_IDENTITY_AWARE`` takes effect without a restart. The per-call
        ``SEARCH_MAX_CONCURRENT`` is applied to the shared semaphore; a ceiling
        of 0 (unbounded) makes the acquire a no-op (see :class:`LazySemaphore`).

        *build_output* is a synchronous callable that takes the resolved core and
        returns the tool's serialised JSON string; it runs off the loop via
        :func:`~search.offload.run_blocking`. Any contextvar (asker, api-key id)
        must be read by the caller ON the loop and captured into *build_output* —
        ``run_blocking`` uses ``run_in_executor``, which does not propagate
        contextvars to the worker thread.

        When *bills_llm* is True the per-key spend quota is enforced before the
        body runs (an over-quota key is rejected) and the completed query's
        tokens are recorded after. The three zero-LLM tools pass
        ``bills_llm=False`` and skip both — they make no LLM call and record no
        tokens (spec §5.1). ``semantic_search`` and ``deep_search`` keep
        ``bills_llm=True``; the api-key id and cap come from
        :data:`~search.spend_quota.mcp_api_key_id` (set by the auth middleware)
        and the live ``SEARCH_KEY_DAILY_TOKEN_QUOTA``. Both are no-ops for a
        disabled quota or a cookie caller.
        """
        core = await run_blocking(lambda: resolve_core(app_db_path))
        api_key_id = mcp_api_key_id.get()
        quota = core.settings.SEARCH_KEY_DAILY_TOKEN_QUOTA
        if bills_llm:
            # Pre-check BEFORE the body runs so an over-quota key never spends a
            # token. A QuotaExceededError becomes a clear tool error — the
            # message carries no secret, so it is surfaced verbatim.
            try:
                await check_quota(
                    api_key_id=api_key_id, quota=quota, app_db_path=app_db_path
                )
            except QuotaExceededError as exc:
                raise ValueError(
                    "Daily LLM token quota for this API key has been reached; "
                    "it resets at UTC midnight."
                ) from exc
        search_semaphore.set_limit(core.settings.SEARCH_MAX_CONCURRENT)
        async with search_semaphore.acquire():
            output = await run_blocking(lambda: build_output(core))
        if bills_llm:
            # Record the query's tokens against the key's daily bucket
            # (best-effort; a no-op for a disabled quota / cookie caller). The
            # token total is read from the serialised result's cost summary.
            await record_usage(
                api_key_id=api_key_id,
                quota=quota,
                tokens=_total_tokens(output),
                app_db_path=app_db_path,
            )
        return output

    async def _dispatch(
        *,
        query: str,
        filters: dict[str, Any] | None,
        core_call: Callable[
            [SearchCore, str, SearchFilters | None, str | None], SearchResult
        ],
        error_event: str,
    ) -> str:
        """Run a query-shaped LLM-billed tool (``semantic_search``/``deep_search``).

        The caller's identity is read from :data:`~search.identity.mcp_asker`
        (set by the auth middleware) HERE on the loop, then resolved per the live
        ``SEARCH_IDENTITY_AWARE`` inside the off-loop body via the pure
        :func:`~search.identity.resolve_asker` — so the contextvar is never read
        from the worker thread (``run_blocking`` does not propagate it).
        """
        raw_asker = mcp_asker.get()

        def _build(core: SearchCore) -> str:
            asker = resolve_asker(
                raw_asker, identity_aware=core.settings.SEARCH_IDENTITY_AWARE
            )
            return _run_search_tool(
                query=query,
                filters=filters,
                core_call=lambda text, ui_filters, asker_arg: core_call(
                    core, text, ui_filters, asker_arg
                ),
                error_event=error_event,
                asker=asker,
            )

        return await _run_tool(_build, bills_llm=True)

    @mcp.tool(
        name="semantic_search",
        description=(
            "PREFERRED, no-cost search — use for almost every query. Returns "
            "ranked source documents (snippets + Paperless deep-links) matching "
            "the query; no synthesised answer. Makes zero LLM calls and does "
            "not bill the archive owner. Read the sources and synthesise the "
            "answer yourself. Optional 'filters' narrows by correspondent, "
            "document type, tag, or date."
        ),
    )
    async def semantic_search(
        query: str,
        filters: dict[str, Any] | None = None,
    ) -> str:
        """Call core.retrieve (pure RAG, zero LLM) and return the result JSON."""
        # The pure-RAG path makes no LLM call, so the asker (identity for
        # first-person resolution in the planner/judge/synth) is irrelevant —
        # the core_call drops it.
        return await _dispatch(
            query=query,
            filters=filters,
            core_call=lambda core, text, ui_filters, asker: core.retrieve(
                query=text, ui_filters=ui_filters
            ),
            error_event="mcp.semantic_search_error",
        )

    @mcp.tool(
        name="deep_search",
        description=(
            "COSTLY, last-resort search. Runs the archive's server-side agentic "
            "pipeline (planner + judge + synthesiser) and returns a written "
            "answer plus sources. Spends the archive owner's paid LLM API "
            "budget on every call. Prefer semantic_search and synthesise "
            "yourself; only call this when you truly cannot. Optional 'filters' "
            "narrows results."
        ),
    )
    async def deep_search(
        question: str,
        filters: dict[str, Any] | None = None,
    ) -> str:
        """Call core.answer and return the SearchResult as JSON."""
        return await _dispatch(
            query=question,
            filters=filters,
            core_call=lambda core, text, ui_filters, asker: core.answer(
                query=text, ui_filters=ui_filters, asker=asker
            ),
            error_event="mcp.deep_search_error",
        )

    @mcp.tool(
        name="list_filters",
        description=(
            "Free. Lists every correspondent, document type, and tag in the "
            "archive — each with an id, name, and document count — plus the "
            "archive's date range. Call this first to discover the exact, valid "
            "filter ids before passing correspondent_id, document_type_id, or "
            "tag_ids to the search tools. Makes no LLM call."
        ),
    )
    async def list_filters() -> str:
        """Return the filter catalogue (taxonomy + counts + date range) as JSON."""

        def _build(core: SearchCore) -> str:
            try:
                catalog = core.list_filters()
            except Exception:
                # Outer-boundary catch (CODE_GUIDELINES §6.4): a store fault may
                # carry a filesystem path; log the traceback, return a sanitised
                # error. ``from None`` severs the chain deliberately.
                log.exception("mcp.list_filters_error")
                raise ValueError("list_filters failed — see server logs") from None
            return json.dumps(
                {
                    "correspondents": [
                        dataclasses.asdict(f) for f in catalog.correspondents
                    ],
                    "document_types": [
                        dataclasses.asdict(f) for f in catalog.document_types
                    ],
                    "tags": [dataclasses.asdict(f) for f in catalog.tags],
                    "date_range": {
                        "earliest": catalog.earliest,
                        "latest": catalog.latest,
                    },
                }
            )

        return await _run_tool(_build, bills_llm=False)

    @mcp.tool(
        name="keyword_search",
        description=(
            "Free. Exact full-text keyword search over document content plus "
            "title/correspondent/type, optionally narrowed by correspondent_id, "
            "document_type_id, tag_ids, date_from/date_to; returns a ranked "
            "DOCUMENT list (not passages). Use for exact terms, names, or "
            "reference numbers, or to enumerate/filter (e.g. every document "
            "tagged X from 2024). Omit 'query' to list documents by filter "
            "alone. Discover valid filter ids with list_filters. Makes no LLM "
            "call. 'limit' defaults to 20 (max 50); 'offset' paginates."
        ),
    )
    async def keyword_search(
        query: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> str:
        """Call core.keyword_search (FTS/browse, zero LLM) and return JSON."""
        bounded_limit = max(1, min(int(limit), 50))
        bounded_offset = max(0, int(offset))
        ui_filters = _to_search_filters(filters)

        def _build(core: SearchCore) -> str:
            try:
                page = core.keyword_search(
                    query, ui_filters, bounded_limit, bounded_offset
                )
            except Exception:
                # Outer-boundary catch (CODE_GUIDELINES §6.4): sanitise any
                # store fault; the traceback is logged, the client gets a
                # generic message. ``from None`` severs the chain.
                log.exception("mcp.keyword_search_error")
                raise ValueError("keyword search failed — see server logs") from None
            base = core.settings.PAPERLESS_PUBLIC_URL
            return json.dumps(
                {
                    "documents": [
                        {
                            "document_id": hit.document.id,
                            "title": hit.document.title,
                            "correspondent": hit.document.correspondent,
                            "document_type": hit.document.document_type,
                            "created": hit.document.created,
                            "snippet": hit.snippet,
                            "paperless_url": _paperless_url(base, hit.document.id),
                        }
                        for hit in page.hits
                    ],
                    "total": page.total,
                    "offset": page.offset,
                    "limit": page.limit,
                }
            )

        return await _run_tool(_build, bills_llm=False)

    @mcp.tool(
        name="fetch_documents",
        description=(
            "Free. Returns the full OCR text of up to 5 documents by id. Each "
            "result carries the content (truncated past 50000 characters, with a "
            "'truncated' flag plus 'total_chars'/'returned_chars'), the title, "
            "page_count, and a Paperless link. Use after a search to read a whole "
            "document; pass the document_ids from search results. An unknown id "
            "returns a per-id 'error' rather than failing the batch. Makes no LLM "
            "call."
        ),
    )
    async def fetch_documents(document_ids: list[int]) -> str:
        """Call core.fetch_documents (Paperless content, zero LLM) → JSON."""
        # Boundary validation BEFORE dispatch so a bad request never resolves the
        # core or opens a Paperless connection. Messages carry no secret, so they
        # surface to the client verbatim.
        if not document_ids:
            raise ValueError("document_ids must contain at least one id")
        if len(document_ids) > 5:
            raise ValueError("fetch_documents accepts at most 5 document_ids per call")
        ids = [int(i) for i in document_ids]
        if any(i <= 0 for i in ids):
            raise ValueError("document_ids must be positive integers")

        def _build(core: SearchCore) -> str:
            # Per-request client (owns an httpx connection); closed in finally,
            # mirroring search.document_routes. The blocking get_document calls
            # run here, already off the event loop via _run_tool's run_blocking.
            client = paperless_factory(core.settings)
            try:
                docs = core.fetch_documents(ids, client)
            finally:
                client.close()
            return json.dumps({"documents": [dataclasses.asdict(doc) for doc in docs]})

        return await _run_tool(_build, bills_llm=False)


def build_mcp_app(
    resolve_core: Callable[[str], SearchCore],
    app_db_path: str,
    *,
    search_semaphore: LazySemaphore,
    paperless_factory: Callable[
        [Settings], PaperlessClient
    ] = _default_paperless_factory,
) -> _McpApp:
    """Build and return the MCP ASGI application (spec §7.2/§7.3).

    Constructs a :class:`~mcp.server.fastmcp.FastMCP` server with the
    streamable-HTTP transport, registers the five tools via
    :func:`_register_search_tools`, and wraps it in
    :class:`_BearerAuthMiddleware` so every MCP request must carry a valid
    session cookie or ``mcp``-scoped API key.

    Args:
        resolve_core: Returns the live :class:`~search.core.SearchCore` for the
            request's ``app.db`` path. Called per tool dispatch so MCP callers
            pick up a hot-loaded configuration change without a restart — the
            same per-request resolution the HTTP ``/api/search`` handler uses.
        app_db_path: The filesystem path to ``app.db``. Passed both to the auth
            middleware (a fresh connection per request resolves a session cookie
            or an API key) and to *resolve_core* on every tool dispatch.
        search_semaphore: The :class:`~search.offload.LazySemaphore` shared with
            the HTTP ``/api/search`` surface, so ``SEARCH_MAX_CONCURRENT`` caps
            both surfaces with one ceiling rather than one per surface (2N).
        paperless_factory: Builds the per-request :class:`PaperlessClient` for
            ``fetch_documents``. Defaults to the production factory; tests inject
            a stub so the tool never makes a real Paperless call.

    Returns:
        An ASGI application wrapping the FastMCP server with cookie/API-key auth.
    """
    mcp = FastMCP(
        name="paperless-search",
        instructions=(
            "Search and read a personal Paperless-ngx document archive. Five "
            "tools; only deep_search is billed.\n\n"
            "- semantic_search(query, filters?) — DEFAULT, free. Hybrid "
            "vector+keyword retrieval; returns the most relevant passages (with "
            "Paperless links) for a natural-language question. No LLM billed — "
            "read the passages and answer yourself. Use for almost every "
            "question.\n"
            "- keyword_search(query?, filters?, limit?, offset?) — free. Exact "
            "full-text search over document content plus title/correspondent/"
            "type, optionally filtered by correspondent_id, document_type_id, "
            "tag_ids, date_from/date_to; returns a ranked DOCUMENT list (not "
            "passages). Use for exact terms, names, reference numbers, or to "
            "enumerate/filter (e.g. every document tagged X from 2024). Omit "
            "query to list documents by filter alone.\n"
            "- fetch_documents(document_ids) — free. Full OCR text of up to 5 "
            "documents by id (truncated past ~50k characters, flagged). Use "
            "after a search to read a whole document.\n"
            "- list_filters() — free. Every correspondent, document type, and "
            "tag in the archive (with counts) plus the date range. Call first "
            "to discover exact, valid filter ids before filtering.\n"
            "- deep_search(question, filters?) — COSTLY, last resort. Runs the "
            "archive's server-side agentic pipeline and returns a written "
            "answer; spends the owner's paid LLM budget every call. Prefer "
            "semantic_search + your own synthesis; use only when explicitly "
            "asked for the archive to answer itself.\n\n"
            "Default to semantic_search. Discover filters with list_filters. "
            "Read whole documents with fetch_documents. Reach for deep_search "
            "only with a concrete reason the free tools cannot serve."
        ),
        stateless_http=True,
        # streamable_http_path stays at FastMCP's default "/mcp": the app
        # factory attaches this app as an exact-path Route at "/mcp" (NOT an
        # app.mount), and a Route forwards the unmodified path, so the inner
        # route must itself be "/mcp". (Mounting under "/mcp" would instead
        # double-prefix to "/mcp/mcp" and never serve the bare "/mcp" a client
        # POSTs to — see search.api.create_app.)
        #
        # Disable FastMCP's DNS-rebinding Host/Origin check. It auto-enables for
        # the default 127.0.0.1 bind with a localhost-only allowlist, which 421s
        # every real request (Host: search.rosset.ie behind the reverse proxy).
        # It is redundant here: the bearer-auth middleware (below) rejects any
        # request without an mcp-scoped key or session cookie BEFORE the
        # transport runs, the reverse proxy controls the Host, and the SPA's
        # SameSite=Strict cookie + CSP connect-src 'self' already block
        # cross-origin browser calls — so the rebinding threat model is covered.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    _register_search_tools(
        mcp, resolve_core, app_db_path, search_semaphore, paperless_factory
    )
    return _McpApp(mcp, app_db_path)
