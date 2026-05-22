"""MCP endpoint for the search server (spec §7.2/§7.3).

``build_mcp_app`` constructs a FastMCP server with the streamable-HTTP transport
and wraps it in a bearer-token authentication middleware.  The returned ASGI
application is mounted at ``/mcp`` by the HTTP server; this module has no
dependency on ``search/api.py``.

Two tools are exposed:

- ``search_documents(query, filters?)`` — calls ``core.retrieve()``.  Returns
  ranked source documents without a synthesised answer; the calling agent
  synthesises its own answer, saving an LLM call (spec §7.2).
- ``ask_documents(question, filters?)`` — calls ``core.answer()``.  Returns the
  full result including the synthesised answer (spec §7.2).

Both tools share one body helper (:func:`_run_search_tool`): length-check the
query at the boundary, convert the optional filters, invoke the core method,
serialise the result, and turn any failure into a sanitised tool error.

Authentication (web-redesign §5):
  Every request must carry either a browser ``search_session`` cookie or an
  ``Authorization: Bearer sk-pls-...`` API key whose scopes include ``mcp``.
  The middleware calls :func:`search.sessions.resolve_session` and
  :func:`search.api_keys.resolve_api_key` and returns HTTP 401 without
  reaching the MCP handler if neither credential is valid. The legacy
  ``SEARCH_API_KEY`` was retired in Wave 3. No secret is ever logged.

Allowed deps: search (core, api_keys, auth, sessions, models, wire), store
    (SearchFilters), appdb (connection), mcp SDK, starlette. The ``app.db``
    path is injected by the app factory; this module owns no SQL and opens a
    fresh connection per request, mirroring ``search.deps.get_app_db``.
Forbidden: FastAPI (api.py), direct LLM/HTTP calls.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from appdb.connection import connect
from search.api_keys import SCOPE_MCP, resolve_api_key
from search.auth import SESSION_COOKIE_NAME, extract_bearer
from search.deps import refresh_last_seen
from search.models import SearchResult
from search.sessions import resolve_session
from search.wire import MAX_QUERY_LENGTH, FilterRequest, to_search_filters
from store import SearchFilters

if TYPE_CHECKING:
    from common.config import Settings
    from search.core import SearchCore

log = structlog.get_logger(__name__)

# The path at which the streamable-HTTP MCP transport listens.  The session
# manager is mounted here within the Starlette sub-app returned by
# streamable_http_app().
_MCP_PATH = "/mcp"


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

        authenticated = self._is_authenticated(bearer, cookie)

        if not authenticated:
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

        await self._app(scope, receive, send)

    def _is_authenticated(self, bearer: str | None, cookie: str | None) -> bool:
        """Return whether the request carries a valid credential.

        Authenticated when EITHER a browser ``search_session`` cookie resolves
        to an active user (a human, not scope-limited) OR an API key resolves
        AND that key carries the ``mcp`` scope. A key without ``mcp`` — e.g. an
        API-only key — cannot reach ``/mcp`` (web-redesign §5). The ``app.db``
        lookup uses a fresh per-request connection, closed before returning.

        Args:
            bearer: The extracted ``Authorization: Bearer`` token, or ``None``.
            cookie: The raw ``search_session`` cookie value, or ``None``.

        Returns:
            ``True`` when the request is authorised, ``False`` otherwise.
        """
        app_db = connect(self._app_db_path)
        try:
            if resolve_session(app_db, cookie) is not None:
                # Refresh last_seen_at so MCP-only users do not have a frozen
                # timestamp — mirrors what search.deps.resolve_caller does for
                # the REST surface (CODE_GUIDELINES §10).
                refresh_last_seen(app_db, cookie)
                return True
            resolved = resolve_api_key(app_db, bearer)
            return resolved is not None and SCOPE_MCP in resolved.scopes
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
    """
    return json.dumps(dataclasses.asdict(result))


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
    core_call: Callable[[str, SearchFilters | None], SearchResult],
    error_event: str,
) -> str:
    """Run one search-tool body: validate, convert, invoke core, serialise.

    The shared body of both MCP tools.  It length-checks *query* at the
    boundary (§10.4), converts the optional *filters*, invokes *core_call*, and
    serialises the result.  Any failure from the core is logged with its full
    traceback server-side and surfaced to the MCP client as a sanitised
    :class:`ValueError` carrying no internal detail.

    Args:
        query: The user's query or question.
        filters: The optional raw filters dict from the tool call.
        core_call: The :class:`~search.core.SearchCore` method to invoke —
            ``retrieve`` for ``search_documents``, ``answer`` for
            ``ask_documents``.
        error_event: The structured-log event name for a failure.

    Returns:
        The serialised :class:`~search.models.SearchResult` as a JSON string.

    Raises:
        ValueError: When *query* exceeds :data:`~search.wire.MAX_QUERY_LENGTH`,
            or — sanitised — when the core call fails.
    """
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(
            f"query exceeds the maximum length of {MAX_QUERY_LENGTH} characters"
        )

    # rationale: outer-boundary catch (CODE_GUIDELINES §6.4) — this is the MCP
    # protocol boundary.  Raw exception strings from the core (which can carry
    # filesystem paths or internal state) must never reach the MCP client; the
    # full traceback is logged server-side instead.
    try:
        ui_filters = _to_search_filters(filters)
        result = core_call(query, ui_filters)
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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._asgi_app(scope, receive, send)


def _register_search_tools(mcp: FastMCP, core: SearchCore) -> None:
    """Register the two search tools on *mcp*, both backed by *core*.

    Each tool is a thin closure over :func:`_run_search_tool`:
    ``search_documents`` calls ``core.retrieve`` (sources only),
    ``ask_documents`` calls ``core.answer`` (synthesised answer).

    Args:
        mcp: The FastMCP server to register the tools on.
        core: The search pipeline backing both tools.
    """

    @mcp.tool(
        name="search_documents",
        description=(
            "Retrieve ranked source documents matching the query.  Returns "
            "snippets and Paperless deep-links; does not synthesise an answer "
            "— the calling agent synthesises its own (saving one LLM call)."
        ),
    )
    def search_documents(
        query: str,
        filters: dict[str, Any] | None = None,
    ) -> str:
        """Call core.retrieve and return the SearchResult as JSON."""
        return _run_search_tool(
            query=query,
            filters=filters,
            core_call=lambda text, ui_filters: core.retrieve(
                query=text, ui_filters=ui_filters
            ),
            error_event="mcp.search_documents_error",
        )

    @mcp.tool(
        name="ask_documents",
        description=(
            "Ask a question and receive a synthesised answer grounded in the "
            "document archive.  Returns the answer text, ranked source "
            "documents, and execution statistics."
        ),
    )
    def ask_documents(
        question: str,
        filters: dict[str, Any] | None = None,
    ) -> str:
        """Call core.answer and return the SearchResult as JSON."""
        return _run_search_tool(
            query=question,
            filters=filters,
            core_call=lambda text, ui_filters: core.answer(
                query=text, ui_filters=ui_filters
            ),
            error_event="mcp.ask_documents_error",
        )


def build_mcp_app(core: SearchCore, settings: Settings, app_db_path: str) -> _McpApp:
    """Build and return the MCP ASGI application (spec §7.2/§7.3).

    Constructs a :class:`~mcp.server.fastmcp.FastMCP` server with the
    streamable-HTTP transport, registers the two search tools via
    :func:`_register_search_tools`, and wraps it in
    :class:`_BearerAuthMiddleware` so every MCP request must carry a valid
    session cookie or ``mcp``-scoped API key.

    Args:
        core: The :class:`~search.core.SearchCore` orchestrating the search
            pipeline.  Its ``retrieve`` and ``answer`` methods back the tools.
        settings: Application settings passed to FastMCP itself; the auth
            middleware no longer reads any setting directly.
        app_db_path: The filesystem path to ``app.db``, passed to the auth
            middleware so a session cookie or an API key can authenticate an
            MCP request. The middleware opens a fresh connection per request.

    Returns:
        An ASGI application wrapping the FastMCP server with cookie/API-key auth.
    """
    mcp = FastMCP(
        name="paperless-search",
        instructions=(
            "Search and query a personal Paperless-ngx document archive.  "
            "Use search_documents to retrieve relevant sources for your own "
            "synthesis, or ask_documents to get a direct synthesised answer."
        ),
        stateless_http=True,
    )
    _register_search_tools(mcp, core)
    return _McpApp(mcp, app_db_path)
