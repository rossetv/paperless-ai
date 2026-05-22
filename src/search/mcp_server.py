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

Authentication (spec §7.3):
  A request is authorised when it carries EITHER a legacy
  ``Authorization: Bearer <SEARCH_API_KEY>`` token (an admin-equivalent through
  Waves 1-2) OR a browser ``search_session`` cookie that resolves to an active
  user.  The middleware returns HTTP 401 without reaching the MCP handler if
  neither credential is valid.  The token is **never logged**
  (CODE_GUIDELINES §7.4, §10.1).

Allowed deps: search (core, auth, sessions, models, wire), store
    (SearchFilters), mcp SDK, starlette. The ``app.db`` connection is injected
    by the app factory; this module owns no SQL.
Forbidden: FastAPI (api.py), ``sqlite3.connect``, direct LLM/HTTP calls.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from search.auth import SESSION_COOKIE_NAME, extract_bearer, legacy_api_key_user
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
    """ASGI middleware that enforces bearer-token authentication.

    Extracts the ``Authorization: Bearer <token>`` header and the session
    cookie, then authorises a request that carries EITHER a valid legacy
    ``SEARCH_API_KEY`` bearer OR a browser session cookie that resolves to an
    active user.  An unauthenticated request is rejected with HTTP 401 before
    the inner ASGI app is called.

    The token is **never logged** — a failed check records only whether a
    header was present, never its value (CODE_GUIDELINES §7.4).

    Args:
        app: The inner ASGI application to protect.
        settings: Application settings; ``SEARCH_API_KEY`` is read from here.
        app_db: The open ``app.db`` connection, used to resolve a browser
            session cookie to a user.
    """

    def __init__(
        self, app: ASGIApp, settings: Settings, app_db: sqlite3.Connection
    ) -> None:
        self._app = app
        self._settings = settings
        self._app_db = app_db

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        request = Request(scope)
        bearer = extract_bearer(request.headers.get("authorization"))
        cookie = request.cookies.get(SESSION_COOKIE_NAME)

        # Authenticated when EITHER the legacy SEARCH_API_KEY bearer matches
        # OR a browser session cookie resolves to an active user.
        authenticated = (
            legacy_api_key_user(bearer, self._settings.SEARCH_API_KEY) is not None
            or resolve_session(self._app_db, cookie) is not None
        )

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
        raise ValueError("search failed — see server logs")


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
        settings: Application settings for the auth middleware.
        app_db: The open ``app.db`` connection for session-cookie auth.
    """

    def __init__(
        self,
        fastmcp: FastMCP,
        settings: Settings,
        app_db: sqlite3.Connection,
    ) -> None:
        self._fastmcp = fastmcp
        starlette_app = fastmcp.streamable_http_app()
        self._asgi_app: ASGIApp = _BearerAuthMiddleware(starlette_app, settings, app_db)

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


def build_mcp_app(
    core: SearchCore, settings: Settings, app_db: sqlite3.Connection
) -> _McpApp:
    """Build and return the MCP ASGI application (spec §7.2/§7.3).

    Constructs a :class:`~mcp.server.fastmcp.FastMCP` server with the
    streamable-HTTP transport, registers the two search tools via
    :func:`_register_search_tools`, and wraps it in
    :class:`_BearerAuthMiddleware` so every MCP request must carry a valid
    ``Authorization: Bearer`` token.

    Args:
        core: The :class:`~search.core.SearchCore` orchestrating the search
            pipeline.  Its ``retrieve`` and ``answer`` methods back the tools.
        settings: Application settings; ``SEARCH_API_KEY`` is used by the auth
            middleware.
        app_db: The open ``app.db`` connection, passed to the auth
            middleware so a browser session cookie can authenticate an MCP
            request.

    Returns:
        An ASGI application wrapping the FastMCP server with bearer-token auth.
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
    return _McpApp(mcp, settings, app_db)
