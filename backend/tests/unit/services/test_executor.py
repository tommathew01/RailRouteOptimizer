"""Search executor shutdown: drain running searches, then cancel (docs/08 D-37)."""

from __future__ import annotations

import asyncio
import uuid

from app.services.executor import InProcessExecutor


async def test_shutdown_lets_running_searches_finish_within_the_grace_period() -> None:
    executor = InProcessExecutor(max_concurrent=2, shutdown_grace_seconds=5)
    finished: list[str] = []

    async def search() -> None:
        await asyncio.sleep(0.05)
        finished.append("done")

    await executor.submit(uuid.uuid4(), search)
    await asyncio.sleep(0)  # started
    await executor.aclose()
    assert finished == ["done"]


async def test_searches_still_running_after_the_grace_period_are_cancelled() -> None:
    executor = InProcessExecutor(max_concurrent=2, shutdown_grace_seconds=0.05)
    cancelled = asyncio.Event()

    async def endless() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    await executor.submit(uuid.uuid4(), endless)
    await asyncio.sleep(0)
    await asyncio.wait_for(executor.aclose(), 2)
    assert cancelled.is_set()


async def test_without_a_grace_period_shutdown_cancels_at_once() -> None:
    executor = InProcessExecutor(max_concurrent=2)
    started = asyncio.Event()

    async def endless() -> None:
        started.set()
        await asyncio.sleep(3600)

    await executor.submit(uuid.uuid4(), endless)
    await started.wait()
    await asyncio.wait_for(executor.aclose(), 0.5)  # no waiting
