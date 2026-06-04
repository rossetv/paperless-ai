"""Event-loop offload primitives shared by the HTTP and MCP search surfaces.

Both the FastAPI route handlers (:mod:`search.routes`) and the MCP tool/auth
layer (:mod:`search.mcp_server`) must keep blocking store/LLM/SQLite work off
the single event loop, and both must bound how many agentic searches run at
once.  This module owns the two primitives that do it — :func:`run_blocking`
and :class:`LazySemaphore` — so the two surfaces share one implementation
rather than each carrying a copy.

It is deliberately free of FastAPI and the MCP SDK so either layer may depend
on it without dragging the other's framework in (``search.mcp_server`` forbids
importing FastAPI).

Allowed deps: stdlib only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, nullcontext
from typing import TypeVar

_T = TypeVar("_T")


async def run_blocking(call: Callable[[], _T]) -> _T:
    """Run a blocking store/LLM/SQLite call on the loop's default executor.

    The store, the LLM client, and the per-request SQLite connections perform
    blocking I/O; running them directly in an async handler would stall the
    event loop and serialise every concurrent caller behind the slow one.
    ``run_in_executor`` moves the work to a worker thread so the loop stays
    free.  The return type is preserved so callers need no cast.

    Must be awaited from inside a running event loop.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, call)


class LazySemaphore:
    """An :class:`asyncio.Semaphore` created on first use, not at build time.

    A semaphore must be bound to the event loop that awaits it, but the search
    router and the MCP app are both built before the serving loop exists, so
    the semaphore is created lazily on the first :meth:`acquire`.  asyncio's
    single-threaded contract means only one coroutine touches the internal
    state at a time — no lock is needed.

    Unbounded mode: a ceiling of ``0`` (or any non-positive value) means
    "no limit", matching :class:`common.concurrency.ConcurrencyGuard` and the
    ``SEARCH_MAX_CONCURRENT`` / ``EMBEDDING_MAX_CONCURRENT`` contract.  In that
    mode :meth:`acquire` returns a no-op context manager — an
    ``asyncio.Semaphore(0)`` would instead block the very first acquirer
    forever.

    Hot-reloadable: :meth:`set_limit` swaps in a new ceiling when
    ``SEARCH_MAX_CONCURRENT`` changes via the Settings API (web-redesign §5,
    Wave 4).  In-flight acquisitions on the *old* semaphore complete on the old
    limit and release into the old object (it is reachable via the awaiting
    coroutines' local frames); new acquisitions hit the new semaphore.  The
    brief window where both are alive is bounded by the longest in-flight
    search, with the new cap fully in force for every new request — no restart.

    Args:
        max_concurrent: The initial simultaneous-holder ceiling; ``0`` or
            negative means unbounded.
    """

    def __init__(self, max_concurrent: int) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore: asyncio.Semaphore | None = None

    def set_limit(self, max_concurrent: object) -> None:
        """Replace the ceiling. Idempotent when *max_concurrent* is unchanged.

        Called per request before :meth:`acquire`; the cheap equality check
        keeps the steady-state cost at one ``int`` compare. A change builds a
        fresh semaphore on the next acquire — see the class docstring for the
        old/new overlap window discussion.

        A value that does not coerce to ``int`` is ignored — keeps stub cores
        in unit tests from crashing the handler with a ``TypeError`` out of
        :class:`asyncio.Semaphore`.
        """
        try:
            new_limit = int(max_concurrent)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            return
        if new_limit == self._max_concurrent:
            return
        self._max_concurrent = new_limit
        # Drop the existing semaphore so the next acquire builds a new one at
        # the new limit. In-flight holders of the old object complete as they
        # were (they captured the old reference); only new requests touch the
        # replacement.
        self._semaphore = None

    def acquire(self) -> AbstractAsyncContextManager[None]:
        """Return an async context manager holding one permit for its block.

        ``async with lazy.acquire():`` bounds the body to the current ceiling.
        When the ceiling is non-positive the returned context manager is a
        no-op (unbounded) — never an ``asyncio.Semaphore(0)``, which would
        deadlock the first acquirer.
        """
        if self._max_concurrent <= 0:
            return nullcontext()
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore
