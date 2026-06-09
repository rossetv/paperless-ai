"""Asker-identity resolution for the search pipeline.

The authenticated user's account ``display_name`` is the "who is asking" signal
threaded into the planner and answer prompts (and the cache key) as an ``asker``
string. Because the name is user-set input flowing into the LLM control plane,
it is sanitised before use — a malicious name must not be able to open a
multi-line instruction block or forge the synthesiser's data fence.

The :data:`mcp_asker` ContextVar carries the resolved asker from the MCP auth
middleware (raw ASGI, no FastAPI dependency injection) to the MCP tool handlers
that run downstream in the same async context.

Allowed deps: contextvars, typing (leaf module). Forbidden: common.config,
fastapi, sqlite3.
"""

from __future__ import annotations

from contextvars import ContextVar

# Carries the sanitised asker from the MCP auth middleware to the tool handlers
# (the tools then apply the SEARCH_IDENTITY_AWARE gate via the live settings).
mcp_asker: ContextVar[str | None] = ContextVar("mcp_asker", default=None)

# Upper bound on an injected display name — a name, not a paragraph.
_MAX_ASKER_CHARS = 80


def sanitise_display_name(name: str | None) -> str | None:
    """Return a prompt-safe single-line display name, or None.

    Collapses all whitespace (including newlines) to single spaces, removes the
    angle-bracket fence markers the synthesiser data fence uses, and caps the
    length. Returns None for an absent, empty, or whitespace-only name (and when
    sanitising leaves nothing), so callers treat "no usable name" uniformly.
    """
    if name is None:
        return None
    collapsed = " ".join(name.split())
    # Strip the fence-marker characters so a name can never open or close the
    # synthesiser's "<<<DATA nonce>>>" data region.
    collapsed = collapsed.replace("<<<", "").replace(">>>", "").strip()
    if not collapsed:
        return None
    return collapsed[:_MAX_ASKER_CHARS].strip()


def resolve_asker(display_name: str | None, *, identity_aware: bool) -> str | None:
    """Resolve the asker to inject, honouring the SEARCH_IDENTITY_AWARE gate.

    Returns None when identity awareness is off or the display name is unusable;
    otherwise the sanitised display name.
    """
    if not identity_aware:
        return None
    return sanitise_display_name(display_name)
