from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.cache.singleflight import SingleFlight
from app.cache.store import RedisStore, StoreError
from app.core.clock import FrozenClock
from app.providers.errors import ProviderQuotaExhaustedError
from app.services.quota import ProviderQuotaGuard
from tests.integration.conftest import requires_redis

pytestmark = [pytest.mark.integration, requires_redis]


async def test_redis_store_semantics(redis_store: RedisStore) -> None:
    assert await redis_store.set("a", b"1", ttl_seconds=5)
    assert not await redis_store.set("a", b"2", only_if_absent=True)
    assert await redis_store.get("a") == b"1"
    ttl = await redis_store.ttl("a")
    assert ttl is not None
    assert 0 < ttl <= 5
    assert await redis_store.incr("n", ttl_seconds=60) == 1
    assert await redis_store.incr("n", 2, ttl_seconds=1) == 3
    n_ttl = await redis_store.ttl("n")
    assert n_ttl is not None
    assert n_ttl > 1  # EXPIRE NX: the first TTL is kept
    assert not await redis_store.delete_if_equals("a", b"other")
    assert await redis_store.delete_if_equals("a", b"1")
    assert await redis_store.get("a") is None


async def test_quota_guard_is_shared_across_processes(redis_store: RedisStore) -> None:
    clock = FrozenClock(datetime(2026, 11, 8, tzinfo=UTC))
    config = {"window_limit": 2, "window_seconds": 600, "monthly_limit": 50, "backoff_seconds": 60}
    worker_a = ProviderQuotaGuard(redis_store, clock=clock, **config)
    worker_b = ProviderQuotaGuard(redis_store, clock=clock, **config)
    await worker_a.before_request("RAILKIT", "x")
    await worker_b.before_request("RAILKIT", "x")
    with pytest.raises(ProviderQuotaExhaustedError):
        await worker_a.before_request("RAILKIT", "x")


async def test_single_flight_across_processes(redis_store: RedisStore) -> None:
    published: dict[str, str] = {}
    calls = 0

    async def compute() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.1)
        published["k"] = "v"
        return "v"

    async def load_cached() -> str | None:
        return published.get("k")

    a = SingleFlight(redis_store, lock_ttl_seconds=5, poll_interval_seconds=0.02)
    b = SingleFlight(redis_store, lock_ttl_seconds=5, poll_interval_seconds=0.02)
    results = await asyncio.gather(
        a.run("k", compute=compute, load_cached=load_cached),
        b.run("k", compute=compute, load_cached=load_cached),
    )
    assert calls == 1
    assert {value for value, _ in results} == {"v"}


async def test_unreachable_redis_raises_store_error() -> None:
    store = RedisStore.from_url("redis://127.0.0.1:1/0", timeout_seconds=0.2)
    with pytest.raises(StoreError):
        await store.ping()
    await store.aclose()
