"""MCP endpoint for the search server (spec §7.2/§7.3).

``build_mcp_app`` constructs a FastMCP server with the streamable-HTTP transport
and wraps it in a bearer-token authentication middleware.  The returned ASGI
application is mounted at ``/mcp`` by the HTTP server (a later task); this
module has no dependency on ``search/api.py``.

Two tools are exposed:

- ``search_documents(query, filters?)`` — calls ``core.retrieve()``.  Returns
  ranked source documents without a synthesised answer; the calling agent
  synthesises its own answer, saving an LLM call (spec §7.2).
- ``ask_documents(question, filters?)`` — calls ``core.answer()``.  Returns the
  full result including the synthesised answer (spec §7.2).

Authentication (spec §7.3):
  Every request must carry ``Authorization: Bearer <SEARCH_API_KEY>``.  The
  middleware calls :func:`search.auth.is_request_authenticated` and returns
  HTTP 401 without reaching the MCP handler if the token is absent or invalid.
  The token is **never logged** (CODE_GUIDELINES §7.4, §10.1).

Allowed deps: search (core, auth, models), store (reader), mcp SDK, starlette.
Forbidden: FastAPI (api.py), sqlite3, direct LLM/HTTP calls.
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Any

import structlog
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from search.auth import SESSION_COOKIE_NAME, extract_bearer, is_request_authenticated

if TYPE_CHECKING:
    from common.config import Settings
    from search.core import SearchCore

log = structlog.get_logger(__name__)

# The path at which the streamable-HTTP MCP transport listens.  The session
# manager is mounted here within the Starlette sub-app returned by
# streamable_http_app().
_MCP_PATH = "/mcp"

# Maximum query/question length enforced at the MCP boundary (§10.4).
# Must match wire.SearchRequest.query max_length so both HTTP and MCP paths
# apply the same documented limit.
_MAX_QUERY_LENGTH = 4000


# ---------------------------------------------------------------------------
# ASGI bearer-token middleware
# ---------------------------------------------------------------------------


class _BearerAuthMiddleware:
    """ASGI middleware that enforces bearer-token authentication.

    Extracts the ``Authorization: Bearer <token>`` header (and the session
    cookie as a fallback) and delegates the credential check to
    :func:`search.auth.is_request_authenticated`.  An unauthenticated request
    is rejected with HTTP 401 before the inner ASGI app is called.

    The token is **never logged** — a failed check records only whether a
    header was present, never its value (CODE_GUIDELINES §7.4).

    Args:
        app: The inner ASGI application to protect.
        settings: Application settings; ``SEARCH_API_KEY`` is read from here.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self._app = app
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        request = Request(scope)
        bearer = extract_bearer(request.headers.get("authorization"))
        cookie = request.cookies.get(SESSION_COOKIE_NAME)

        if not is_request_authenticated(bearer=bearer, cookie=cookie, settings=self._settings):
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
# SearchResult serialisation
# ---------------------------------------------------------------------------


def _serialise_result(result: Any) -> str:
    """Serialise a SearchResult to a JSON string for MCP tool output.

    Uses :func:`dataclasses.asdict` to convert the frozen-dataclass tree to a
    plain dict, then serialises to JSON.  Tuples become lists in the output,
    which is fine for a wire format consumed by JSON clients.
    """
    return json.dumps(dataclasses.asdict(result))


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
    """

    def __init__(self, fastmcp: FastMCP, settings: Settings) -> None:
        self._fastmcp = fastmcp
        starlette_app = fastmcp.streamable_http_app()
        self._asgi_app: ASGIApp = _BearerAuthMiddleware(starlette_app, settings)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._asgi_app(scope, receive, send)


def build_mcp_app(core: SearchCore, settings: Settings) -> _McpApp:
    """Build and return the MCP ASGI application (spec §7.2/§7.3).

    Constructs a :class:`~mcp.server.fastmcp.FastMCP` server with the
    streamable-HTTP transport and registers the two search tools.  The server
    is wrapped in :class:`_BearerAuthMiddleware` so every MCP request must
    carry a valid ``Authorization: Bearer`` token.

    The returned :class:`_McpApp` is a mountable ASGI application; the HTTP
    server in a later task mounts it at ``/mcp``.  This function does not
    depend on or import ``search/api.py``.

    Args:
        core: The :class:`~search.core.SearchCore` orchestrating the search
            pipeline.  Its ``retrieve`` and ``answer`` methods are called by
            the two MCP tools.
        settings: Application settings; ``SEARCH_API_KEY`` is used by the auth
            middleware.

    Returns:
        An ASGI application wrapping the FastMCP server with bearer-token auth.
    """
    from store.reader import SearchFilters

    mcp = FastMCP(
        name="paperless-search",
        instructions=(
            "Search and query a personal Paperless-ngx document archive.  "
            "Use search_documents to retrieve relevant sources for your own "
            "synthesis, or ask_documents to get a direct synthesised answer."
        ),
        stateless_http=True,
    )

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
        """Call core.retrieve and return the SearchResult as JSON.

        Args:
            query: The user's search query.
            filters: Optional filters as a dict with keys ``date_from``,
                ``date_to``, ``correspondent_id``, ``document_type_id``,
                ``tag_ids``.  Missing keys default to ``None`` / empty tuple.

        Returns:
            A JSON string of the serialised :class:`~search.models.SearchResult`.
        """
        # Validate length at the MCP boundary (§10.4).
        if len(query) > _MAX_QUERY_LENGTH:
            raise ValueError(
                f"query exceeds the maximum length of {_MAX_QUERY_LENGTH} characters"
            )

        # rationale: outer-boundary catch (CODE_GUIDELINES §6.4) — this is the
        # MCP protocol boundary.  Raw exception strings from core (which can
        # carry filesystem paths or internal state) must never reach the MCP
        # client; the full traceback is logged server-side instead.
        try:
            ui_filters = _dict_to_search_filters(filters, SearchFilters)
            result = core.retrieve(query=query, ui_filters=ui_filters)
            return _serialise_result(result)
        except Exception:
            log.exception("mcp.search_documents_error")
            raise ValueError("search failed — see server logs")

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
        """Call core.answer and return the SearchResult as JSON.

        Args:
            question: The user's question.
            filters: Optional filters as a dict with keys ``date_from``,
                ``date_to``, ``correspondent_id``, ``document_type_id``,
                ``tag_ids``.  Missing keys default to ``None`` / empty tuple.

        Returns:
            A JSON string of the serialised :class:`~search.models.SearchResult`.
        """
        # Validate length at the MCP boundary (§10.4).
        if len(question) > _MAX_QUERY_LENGTH:
            raise ValueError(
                f"question exceeds the maximum length of {_MAX_QUERY_LENGTH} characters"
            )

        # rationale: outer-boundary catch (CODE_GUIDELINES §6.4) — this is the
        # MCP protocol boundary.  Raw exception strings from core (which can
        # carry filesystem paths or internal state) must never reach the MCP
        # client; the full traceback is logged server-side instead.
        try:
            ui_filters = _dict_to_search_filters(filters, SearchFilters)
            result = core.answer(query=question, ui_filters=ui_filters)
            return _serialise_result(result)
        except Exception:
            log.exception("mcp.ask_documents_error")
            raise ValueError("search failed — see server logs")

    return _McpApp(mcp, settings)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dict_to_search_filters(
    raw: dict[str, Any] | None,
    search_filters_cls: type,
) -> Any | None:
    """Convert an optional filters dict to a SearchFilters instance.

    Returns ``None`` when *raw* is ``None`` or empty, so no filters are applied.
    Unknown keys in *raw* are silently ignored (the MCP boundary is lenient on
    extra fields; the validation contract is that recognised fields are typed
    correctly).

    Args:
        raw: The raw filters dict from the tool call, or ``None``.
        search_filters_cls: The :class:`~store.reader.SearchFilters` class,
            injected to avoid a top-level circular import.

    Returns:
        A :class:`~store.reader.SearchFilters` instance, or ``None``.
    """
    if not raw:
        return None

    tag_ids_raw = raw.get("tag_ids") or []
    return search_filters_cls(
        date_from=raw.get("date_from"),
        date_to=raw.get("date_to"),
        correspondent_id=raw.get("correspondent_id"),
        document_type_id=raw.get("document_type_id"),
        tag_ids=tuple(int(t) for t in tag_ids_raw),
    )
