"""Tests for the shared event-loop offload helpers (search.offload).

Covers:
- run_blocking() returns the call's value and runs it off the loop thread.
- LazySemaphore bounds concurrency at its ceiling.
- A ceiling of 0 means unbounded (a no-op acquire) — NOT asyncio.Semaphore(0),
  which would deadlock the first acquirer.
- set_limit() switches the ceiling.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from search.offload import LazySemaphore, run_blocking


async def _peak_concurrency(semaphore: LazySemaphore, workers: int) -> int:
    """Run *workers* coroutines under *semaphore*; return the max seen at once."""
    active = 0
    peak = 0

    async def worker() -> None:
        nonlocal active, peak
        async with semaphore.acquire():
            active += 1
            peak = max(peak, active)
            # Yield so siblings get a chance to run inside their own acquire.
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(workers)))
    return peak


@pytest.mark.anyio
async def test_run_blocking_returns_the_call_result() -> None:
    assert await run_blocking(lambda: 6 * 7) == 42


@pytest.mark.anyio
async def test_run_blocking_runs_off_the_event_loop_thread() -> None:
    """The call executes on a worker thread, not the loop thread."""
    loop_thread = threading.current_thread().name
    worker_thread = await run_blocking(lambda: threading.current_thread().name)
    assert worker_thread != loop_thread


@pytest.mark.anyio
async def test_lazy_semaphore_bounds_concurrency() -> None:
    """A ceiling of 1 serialises; 2 lets at most two run at once."""
    assert await _peak_concurrency(LazySemaphore(1), workers=4) == 1
    assert await _peak_concurrency(LazySemaphore(2), workers=4) == 2


@pytest.mark.anyio
async def test_lazy_semaphore_zero_is_unbounded() -> None:
    """A ceiling of 0 never blocks — all workers run concurrently, no deadlock.

    Regression guard: a naive asyncio.Semaphore(0) would block the first
    acquirer forever; the unbounded contract (0 == no limit) must hold.
    """
    assert await _peak_concurrency(LazySemaphore(0), workers=5) == 5


@pytest.mark.anyio
async def test_set_limit_switches_to_unbounded() -> None:
    semaphore = LazySemaphore(1)
    semaphore.set_limit(0)
    assert await _peak_concurrency(semaphore, workers=5) == 5


@pytest.mark.anyio
async def test_set_limit_raises_the_ceiling() -> None:
    """A higher ceiling lets more workers run at once on the next acquire."""
    semaphore = LazySemaphore(1)
    semaphore.set_limit(3)
    assert await _peak_concurrency(semaphore, workers=4) == 3
