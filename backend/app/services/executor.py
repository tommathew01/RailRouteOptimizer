"""Search execution strategies (decision D-06).

``InProcessExecutor`` runs searches as background asyncio tasks (bounded concurrency) so the API
can answer ``202 Accepted`` immediately. ``InlineExecutor`` runs them before returning — used by
``SEARCH_EXECUTION_MODE=sync`` for tests and simple development. A Redis-backed worker (e.g. Arq)
can implement the same protocol later without touching the orchestrator.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

logger = logging.getLogger(__name__)

Job = Callable[[], Awaitable[None]]


class SearchExecutor(Protocol):
    @property
    def runs_inline(self) -> bool: ...

    async def submit(self, search_id: uuid.UUID, job: Job) -> None: ...

    async def aclose(self) -> None: ...


class InlineExecutor:
    @property
    def runs_inline(self) -> bool:
        return True

    async def submit(self, search_id: uuid.UUID, job: Job) -> None:
        await job()

    async def aclose(self) -> None:
        return None


class InProcessExecutor:
    def __init__(self, *, max_concurrent: int) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def runs_inline(self) -> bool:
        return False

    async def submit(self, search_id: uuid.UUID, job: Job) -> None:
        async def runner() -> None:
            async with self._semaphore:
                await job()

        task = asyncio.create_task(runner(), name=f"journey-search-{search_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """Await every running search (tests and graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
