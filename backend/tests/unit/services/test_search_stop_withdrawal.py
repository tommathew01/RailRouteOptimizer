"""Stopping a search withdraws requests that were not sent yet (docs/08 D-35).

Real AvailabilityService + RailKit adapter over an httpx mock transport with one connection slot:
a call still waiting for the slot when its search is stopped is never sent, costs nothing, and
another search sharing the same in-process single-flight is not affected.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import httpx

from app.cache.singleflight import SingleFlight
from app.cache.store import MemoryStore
from app.cache.typed_cache import TypedCache
from app.core.clock import FrozenClock
from app.domain.enums import Quota
from app.domain.models import SegmentKey
from app.integrations.railkit.client import RailKitHttpClient
from app.integrations.railkit.provider import RailKitProvider
from app.repositories.memory import InMemoryPersistence
from app.services.availability import AvailabilityService, SegmentRequest
from app.services.quota import SearchBudget
from tests.unit.providers.railkit_helpers import load_fixture

CLOCK = FrozenClock(datetime(2026, 11, 8, 10, 0, tzinfo=UTC))
DAY = date(2026, 9, 1)
REQUEST = SegmentRequest(SegmentKey("12904", DAY, "NZM", "BDTS", "3A", Quota.GENERAL), DAY)


class SlowTransport:
    """``/hold`` blocks until released (it occupies the only connection slot); seat checks
    answer with the documented sample, or fail with 503 when ``busy``."""

    def __init__(self, *, busy: bool = False) -> None:
        self.release = asyncio.Event()
        self.holding = asyncio.Event()
        self.paths: list[str] = []
        self.busy = busy

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.url.path == "/hold":
            self.holding.set()
            await self.release.wait()
            return httpx.Response(200, json={"success": True, "data": {}})
        if self.busy:
            return httpx.Response(503, json={"success": False, "error": "busy"})
        return httpx.Response(200, json=load_fixture("seat_availability_docs.json"))


def build(
    transport: SlowTransport, *, retries: int = 1
) -> tuple[AvailabilityService, RailKitHttpClient]:
    async def no_sleep(_: float) -> None:
        return None

    client = RailKitHttpClient(
        base_url="https://api.railkit.test",
        api_key="rk_test_key_0123456789",
        timeout=httpx.Timeout(5.0),
        max_retries=retries,
        backoff_seconds=0.0,
        max_concurrency=1,
        transport=httpx.MockTransport(transport),
        sleep=no_sleep,
    )
    store = MemoryStore()
    service = AvailabilityService(
        provider=RailKitProvider(client, clock=CLOCK, fare_currency="INR"),
        cache=TypedCache(store),
        flight=SingleFlight(store, lock_ttl_seconds=60),
        persistence=InMemoryPersistence(),
        clock=CLOCK,
        ttl_seconds=120,
    )
    return service, client


async def test_a_queued_request_of_a_stopped_search_is_never_sent() -> None:
    transport = SlowTransport()
    service, client = build(transport)
    holder = asyncio.create_task(client.get_data("hold", "/hold"))
    await transport.holding.wait()

    budget = SearchBudget(10)
    check = asyncio.create_task(service.check(REQUEST, budget=budget))
    await asyncio.sleep(0.05)  # reserved, now waiting for the connection slot
    budget.stop()  # the user presses "Stop search"
    transport.release.set()
    result = await check
    await holder

    assert result.outcome is None  # not checked — never "unavailable"
    assert transport.paths == ["/hold"]  # the seat request was never sent
    assert (budget.used, budget.checks, budget.attempts) == (0, 0, 0)  # and cost nothing


async def test_another_search_sharing_the_request_still_gets_its_answer() -> None:
    transport = SlowTransport()
    service, client = build(transport)
    holder = asyncio.create_task(client.get_data("hold", "/hold"))
    await transport.holding.wait()

    stopped, other = SearchBudget(10), SearchBudget(10)
    first = asyncio.create_task(service.check(REQUEST, budget=stopped))
    await asyncio.sleep(0.05)
    second = asyncio.create_task(service.check(REQUEST, budget=other))  # joins first's flight
    await asyncio.sleep(0.05)
    stopped.stop()
    transport.release.set()
    first_result, second_result = await asyncio.gather(first, second)
    await holder

    assert first_result.outcome is None
    assert second_result.succeeded  # did not inherit the other user's stop
    assert transport.paths.count("/api/v1/seats/12904/NZM/BDTS/01-09-2026/3A/GN") == 1
    assert (other.used, other.checks) == (1, 1)
    assert stopped.used == 0


async def test_after_a_stop_nothing_new_starts_and_failed_calls_are_not_retried() -> None:
    transport = SlowTransport(busy=True)
    service, _ = build(transport, retries=3)
    budget = SearchBudget(10)
    budget.stop()
    assert (await service.check(REQUEST, budget=budget)).outcome is None
    assert transport.paths == []

    budget = SearchBudget(10)
    call = await budget.start_call()
    assert call is not None
    budget.stop()
    assert await call.allow_retry() is False  # a retry after the stop is refused
