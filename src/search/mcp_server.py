"""MCP endpoint for the search server, served at ``/mcp``.

Five tools; only ``deep_search`` calls the chat LLM and counts against the
per-key spend quota. Every request needs a session cookie or an API key with
the ``mcp`` scope.
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
from search.wire import (
    MAX_QUERY_LENGTH,
    FilterRequest,
    normalise_query,
    to_search_filters,
)
from store import SearchFilters

if TYPE_CHECKING:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    from common.config import Settings
    from search.core import SearchCore


def _default_paperless_factory(settings: Settings) -> PaperlessClient:
    """Build a real :class:`~common.paperless.PaperlessClient` from *settings*."""
    return PaperlessClient(settings)


log = structlog.get_logger(__name__)


class _BearerAuthMiddleware:
    """Reject with 401 any request lacking a session cookie or ``mcp``-scoped key.

    A failed check logs only whether a header or cookie was present, never its
    value.
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

        # Raw ASGI gets no FastAPI threadpool offload, so do it here.
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

        # The tool handlers read these contextvars; reset in finally so they
        # cannot leak into the next request sharing this async context.
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
        """Return ``(authenticated, display_name, api_key_id)`` for the request.

        The display name is unsanitised; :func:`~search.identity.resolve_asker`
        sanitises it. ``api_key_id`` is ``None`` for a cookie caller, whom the
        spend quota never limits.
        """
        app_db = connect(self._app_db_path)
        try:
            user = resolve_session(app_db, cookie)
            if user is not None:
                # Otherwise MCP-only users would have a frozen last-seen time.
                refresh_last_seen(app_db, cookie)
                return True, user.display_name, None
            resolved = resolve_api_key(app_db, bearer)
            if resolved is not None and SCOPE_MCP in resolved.scopes:
                return True, resolved.owner_display_name, resolved.api_key_id
            return False, None, None
        finally:
            app_db.close()


def _serialise_result(result: SearchResult) -> str:
    """Serialise a SearchResult to JSON, dropping the SPA-only reasoning trace."""
    payload = dataclasses.asdict(result)
    stats = payload.get("stats")
    if isinstance(stats, dict):
        stats.pop("trace", None)
    return json.dumps(payload)


def _total_tokens(serialised_result: str) -> int:
    """Read ``stats.cost.tokens.total`` from a serialised tool result.

    Returns ``0`` when it cannot be read: usage recording is best-effort and
    must not break the tool response.
    """
    try:
        payload = json.loads(serialised_result)
        total = payload["stats"]["cost"]["tokens"]["total"]
    except (ValueError, TypeError, KeyError):
        return 0
    return total if isinstance(total, int) and total >= 0 else 0


def _to_search_filters(raw: dict[str, Any] | None) -> SearchFilters | None:
    """Validate an untyped filters dict via :class:`~search.wire.FilterRequest`.

    Unknown keys are ignored; ``None`` or an empty dict means no filters.
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
    """Normalise the query, run *core_call* and serialise the result.

    A core failure is logged server-side and raised to the client as a
    sanitised :class:`ValueError` with no internal detail.
    """
    # Outside the try so an invalid query gets its own message, not the
    # sanitised fallback.
    query = normalise_query(query)

    try:
        ui_filters = _to_search_filters(filters)
        result = core_call(query, ui_filters, asker)
        return _serialise_result(result)
    except Exception:
        log.exception(error_event)
        # The original may carry filesystem paths or internal state.
        raise ValueError("search failed — see server logs") from None


class _McpApp:
    """The auth-wrapped ASGI app, keeping the FastMCP instance for tests."""

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

        A parent app never runs an attached sub-app's lifespan, so
        ``search.api.create_app`` must run this manager itself.
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
    """Register the MCP tools on *mcp*.

    The core is resolved per call so a saved configuration change reaches MCP
    callers on the next call, as on the HTTP surface.
    """

    async def _run_tool(
        build_output: Callable[[SearchCore], str],
        *,
        bills_llm: bool,
        cache_hits: list[None] | None = None,
    ) -> str:
        """Run a tool body off the loop, under the shared concurrency bound.

        *build_output* runs on a worker thread, which does not inherit
        contextvars, so callers must read any contextvar on the loop and
        capture it. With *bills_llm* the per-key spend quota is checked before
        the body (again once the slot is held) and the query's tokens are
        recorded after (none when *cache_hits* shows a cached answer).
        """
        core = await run_blocking(lambda: resolve_core(app_db_path))
        api_key_id = mcp_api_key_id.get()
        quota = core.settings.SEARCH_KEY_DAILY_TOKEN_QUOTA

        async def _enforce_quota() -> None:
            try:
                await check_quota(
                    api_key_id=api_key_id, quota=quota, app_db_path=app_db_path
                )
            except QuotaExceededError as exc:
                raise ValueError(
                    "Daily LLM token quota for this API key has been reached; "
                    "it resets at UTC midnight."
                ) from exc

        if bills_llm:
            await _enforce_quota()
        search_semaphore.set_limit(core.settings.SEARCH_MAX_CONCURRENT)
        async with search_semaphore.acquire():
            if bills_llm:
                # Calls queued for a slot passed the first check before any
                # of them recorded usage; look again now that they have run.
                await _enforce_quota()
            output = await run_blocking(lambda: build_output(core))
            if bills_llm:
                # Still holding the slot, so the next call's check sees this.
                await record_usage(
                    api_key_id=api_key_id,
                    quota=quota,
                    tokens=0 if cache_hits else _total_tokens(output),
                    app_db_path=app_db_path,
                )
        return output

    async def _dispatch(
        *,
        query: str,
        filters: dict[str, Any] | None,
        core_call: Callable[
            [SearchCore, str, SearchFilters | None, str | None, Callable[[], None]],
            SearchResult,
        ],
        error_event: str,
        bills_llm: bool,
    ) -> str:
        """Run a query-shaped tool (``semantic_search``/``deep_search``)."""
        # Read on the loop: the worker thread does not inherit contextvars.
        raw_asker = mcp_asker.get()
        cache_hits: list[None] = []

        def _build(core: SearchCore) -> str:
            asker = resolve_asker(
                raw_asker, identity_aware=core.settings.SEARCH_IDENTITY_AWARE
            )
            return _run_search_tool(
                query=query,
                filters=filters,
                core_call=lambda text, ui_filters, asker_arg: core_call(
                    core,
                    text,
                    ui_filters,
                    asker_arg,
                    lambda: cache_hits.append(None),
                ),
                error_event=error_event,
                asker=asker,
            )

        return await _run_tool(_build, bills_llm=bills_llm, cache_hits=cache_hits)

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
        return await _dispatch(
            query=query,
            filters=filters,
            core_call=lambda core, text, ui_filters, asker, _hit: core.retrieve(
                query=text, ui_filters=ui_filters
            ),
            error_event="mcp.semantic_search_error",
            bills_llm=False,
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
            core_call=lambda core, text, ui_filters, asker, hit: core.answer(
                query=text, ui_filters=ui_filters, asker=asker, on_cache_hit=hit
            ),
            error_event="mcp.deep_search_error",
            bills_llm=True,
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
                # A store fault may carry a filesystem path; sanitise it.
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
        if query is not None and len(query) > MAX_QUERY_LENGTH:
            raise ValueError(
                f"query exceeds the maximum length of {MAX_QUERY_LENGTH} characters"
            )
        bounded_limit = max(1, min(int(limit), 50))
        bounded_offset = max(0, int(offset))
        ui_filters = _to_search_filters(filters)

        def _build(core: SearchCore) -> str:
            try:
                page = core.keyword_search(
                    query, ui_filters, bounded_limit, bounded_offset
                )
            except Exception:
                # A store fault may carry a filesystem path; sanitise it.
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
        # Validate before dispatch so a bad request never opens a Paperless
        # connection.
        if not document_ids:
            raise ValueError("document_ids must contain at least one id")
        if len(document_ids) > 5:
            raise ValueError("fetch_documents accepts at most 5 document_ids per call")
        ids = [int(i) for i in document_ids]
        if any(i <= 0 for i in ids):
            raise ValueError("document_ids must be positive integers")

        def _build(core: SearchCore) -> str:
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
    """Build the auth-wrapped MCP ASGI application.

    *search_semaphore* is shared with the HTTP search route so
    ``SEARCH_MAX_CONCURRENT`` is one cap across both surfaces.
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
        # streamable_http_path stays at the default "/mcp" because
        # search.api.create_app attaches this app as an exact-path Route, which
        # forwards the path unchanged.
        # FastMCP's DNS-rebinding check auto-enables a localhost-only Host
        # allowlist, which 421s every request through the reverse proxy. It is
        # redundant: auth runs before the transport, the proxy controls Host,
        # and the SameSite=Strict cookie plus CSP connect-src 'self' block
        # cross-origin browser calls.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    _register_search_tools(
        mcp, resolve_core, app_db_path, search_semaphore, paperless_factory
    )
    return _McpApp(mcp, app_db_path)
