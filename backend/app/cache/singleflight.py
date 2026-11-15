"""Single-flight request de-duplication (doc 04 §8, doc 06 §3).

Two layers:

1. **In-process**: concurrent callers for the same key in this process share one coroutine.
2. **Distributed** (when the store is shared, e.g. Redis): a ``SET NX PX`` lock; callers that do
   not hold it poll the cache until the holder publishes the result, the lock disappears, or the
   wait times out. On timeout the caller computes itself — quota guards still apply, so a lost
   lock can cost at most one duplicate request, never an unbounded burst.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.cache import keys
from app.cache.store import KeyValueStore, StoreError

logger = logging.getLogger(__name__)
T = TypeVar("T")


class SingleFlight:
    def __init__(
        self,
        store: KeyValueStore,
        *,
        lock_ttl_seconds: float,
        wait_timeout_seconds: float | None = None,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self._store = store
        self._lock_ttl = lock_ttl_seconds
        self._wait_timeout = wait_timeout_seconds or lock_ttl_seconds
        self._poll = poll_interval_seconds
        self._inflight: dict[str, asyncio.Future[Any]] = {}

    async def run(
        self,
        key: str,
        *,
        compute: Callable[[], Awaitable[T]],
        load_cached: Callable[[], Awaitable[T | None]],
    ) -> tuple[T, bool]:
        """Return ``(value, shared)``; ``shared`` is True when another caller did the work."""
        existing = self._inflight.get(key)
        if existing is not None:
            return await asyncio.shield(existing), True

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value, shared = await self._run_distributed(key, compute, load_cached)
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
                future.exception()  # mark retrieved: waiters re-raise it, nobody logs it twice
            raise
        else:
            future.set_result(value)
            return value, shared
        finally:
            self._inflight.pop(key, None)

    async def _run_distributed(
        self,
        key: str,
        compute: Callable[[], Awaitable[T]],
        load_cached: Callable[[], Awaitable[T | None]],
    ) -> tuple[T, bool]:
        if not self._store.distributed:
            return await compute(), False
        lock_key = keys.lock(key)
        token = uuid.uuid4().hex.encode()
        deadline = time.monotonic() + self._wait_timeout
        attempt = 0
        while True:
            if attempt > 0 and (cached := await load_cached()) is not None:
                return cached, True
            try:
                acquired = await self._store.set(
                    lock_key, token, ttl_seconds=self._lock_ttl, only_if_absent=True
                )
            except StoreError:
                logger.warning("single-flight lock unavailable; computing locally")
                return await compute(), False
            if acquired:
                try:
                    # The previous holder may have published just before releasing the lock.
                    if attempt > 0 and (cached := await load_cached()) is not None:
                        return cached, True
                    return await compute(), False
                finally:
                    try:
                        await self._store.delete_if_equals(lock_key, token)
                    except StoreError:
                        logger.warning("could not release single-flight lock")
            if time.monotonic() >= deadline:
                logger.warning("single-flight wait timed out; computing locally")
                return await compute(), False
            attempt += 1
            await asyncio.sleep(self._poll)
