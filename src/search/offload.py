"""Event-loop offload helpers shared by the HTTP and MCP search surfaces.

Kept free of FastAPI and the MCP SDK so either surface can import it without
pulling in the other's framework.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, nullcontext
from typing import TypeVar

_T = TypeVar("_T")


async def run_blocking(call: Callable[[], _T]) -> _T:
    """Run a blocking store/LLM/SQLite call on the loop's default executor.

    Calling these directly in an async handler would stall the event loop and
    serialise every concurrent caller behind the slow one.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, call)


class LazySemaphore:
    """An :class:`asyncio.Semaphore` created on first use, not at build time.

    A semaphore is bound to the loop that awaits it, and the search router and
    MCP app are built before the serving loop exists. A non-positive ceiling
    means unbounded, matching :class:`common.concurrency.ConcurrencyGuard`.

    :meth:`set_limit` swaps in a new ceiling when ``SEARCH_MAX_CONCURRENT``
    changes at runtime. Holders of the old semaphore finish and release into
    it; new acquisitions use the new one.
    """

    def __init__(self, max_concurrent: int) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore: asyncio.Semaphore | None = None

    def set_limit(self, max_concurrent: int) -> None:
        """Replace the ceiling; a no-op when it is unchanged (called per request)."""
        if max_concurrent == self._max_concurrent:
            return
        self._max_concurrent = max_concurrent
        # In-flight holders keep their reference to the old semaphore.
        self._semaphore = None

    def acquire(self) -> AbstractAsyncContextManager[None]:
        """Return an async context manager holding one permit for its block.

        Unbounded mode returns a no-op: ``asyncio.Semaphore(0)`` would block the
        first acquirer forever.
        """
        if self._max_concurrent <= 0:
            return nullcontext()
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore
