"""Per-search accounting of logical checks vs provider HTTP attempts (docs/08 D-28).

Real AvailabilityService + RailKit adapter + global quota guard over an httpx mock transport:
retries are paid from the search budget, the budget is never exceeded, the guard still counts
every attempt, and cache hits / single-flight followers cost nothing.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import httpx

from app.cache.singleflight import SingleFlight
from app.cache.store import MemoryStore
from app.cache.typed_cache import TypedCache
from app.core.clock import FrozenClock
from app.domain.enums import Quota, SegmentQueryOutcome
from app.domain.models import SegmentKey
from app.integrations.railkit.client import PROVIDER_NAME, RailKitHttpClient
from app.integrations.railkit.provider import RailKitProvider
from app.providers.errors import ProviderTimeoutError
from app.providers.mock.provider import MockRailwayProvider
from app.repositories.memory import InMemoryPersistence
from app.services.availability import AvailabilityService, SegmentRequest
from app.services.quota import ProviderQuotaGuard, SearchBudget
from tests.unit.providers.railkit_helpers import Router, json_response, load_fixture

CLOCK = FrozenClock(datetime(2026, 11, 8, 10, 0, tzinfo=UTC))
DAY = date(2026, 9, 1)
BUSY = json_response(503, {"success": False, "error": "busy"})


def ok() -> httpx.Response:
    return json_response(200, load_fixture("seat_availability_docs.json"))


def request(to_station: str = "BDTS") -> SegmentRequest:
    key = SegmentKey("12904", DAY, "NZM", to_station, "3A", Quota.GENERAL)
    return SegmentRequest(key, DAY)


async def _no_sleep(_: float) -> None:
    return None


def build(
    router: Router, *, retries: int = 1, window_limit: int = 1_000
) -> tuple[AvailabilityService, ProviderQuotaGuard]:
    store = MemoryStore()
    guard = ProviderQuotaGuard(
        store,
        clock=CLOCK,
        window_limit=window_limit,
        window_seconds=600,
        monthly_limit=10_000,
        backoff_seconds=300,
    )
    client = RailKitHttpClient(
        base_url="https://api.railkit.test",
        api_key="rk_test_key_0123456789",
        timeout=httpx.Timeout(1.0),
        max_retries=retries,
        backoff_seconds=0.0,
        observer=guard,
        transport=router.transport,
        sleep=_no_sleep,
    )
    provider = RailKitProvider(client, clock=CLOCK, fare_currency="INR")
    service = AvailabilityService(
        provider=provider,
        cache=TypedCache(store),
        flight=SingleFlight(store, lock_ttl_seconds=60),
        persistence=InMemoryPersistence(),
        clock=CLOCK,
        ttl_seconds=120,
    )
    return service, guard


def counts(budget: SearchBudget) -> tuple[int, int, int, int, int]:
    return budget.used, budget.checks, budget.attempts, budget.retries, budget.retries_refused


async def guard_used(guard: ProviderQuotaGuard) -> tuple[int, int]:
    snapshot = await guard.snapshot(PROVIDER_NAME)
    return snapshot.window_used, snapshot.monthly_used


async def test_a_retry_is_charged_to_the_search_budget_and_the_global_guard() -> None:
    router = Router(BUSY, ok())
    service, guard = build(router)
    budget = SearchBudget(5)
    result = await service.check(request(), budget=budget)
    assert result.succeeded
    assert len(router.requests) == 2
    # used, logical checks, HTTP attempts, retries, refused
    assert counts(budget) == (2, 1, 2, 1, 0)
    assert await guard_used(guard) == (2, 2)


async def test_a_retry_is_refused_when_the_search_budget_is_spent() -> None:
    router = Router(BUSY, ok())
    service, guard = build(router)
    budget = SearchBudget(1)
    result = await service.check(request(), budget=budget)
    # The call ends with its real error: the segment is "not checked", never "unavailable".
    assert result.outcome is SegmentQueryOutcome.UPSTREAM_ERROR
    assert result.observation is None
    assert len(router.requests) == 1
    assert counts(budget) == (1, 1, 1, 0, 1)
    assert await guard_used(guard) == (1, 1)


async def test_retries_never_push_a_search_over_its_budget() -> None:
    router = Router(BUSY)  # every attempt fails and wants up to 3 retries
    service, guard = build(router, retries=3)
    budget = SearchBudget(5)
    results = await asyncio.gather(
        *(service.check(request(f"S{i:03}"), budget=budget) for i in range(8))
    )
    assert budget.used == budget.attempts == len(router.requests) <= 5
    assert all(r.outcome is not SegmentQueryOutcome.SUCCESS for r in results)
    assert sum(r.outcome is None for r in results) == 8 - budget.checks  # refused before calling
    assert (await guard_used(guard))[0] == len(router.requests)


async def test_cache_hits_do_not_consume_the_budget() -> None:
    router = Router(ok())
    service, guard = build(router)
    budget = SearchBudget(5)
    first = await service.check(request(), budget=budget)
    second = await service.check(request(), budget=budget)
    assert first.succeeded
    assert not first.cache_hit
    assert second.succeeded
    assert second.cache_hit
    assert counts(budget) == (1, 1, 1, 0, 0)
    assert len(router.requests) == 1
    assert await guard_used(guard) == (1, 1)


async def test_single_flight_followers_share_one_logical_check() -> None:
    router = Router(ok())
    service, _ = build(router)
    budget = SearchBudget(5)
    results = await asyncio.gather(*(service.check(request(), budget=budget) for _ in range(4)))
    assert all(r.succeeded for r in results)
    assert sum(not r.cache_hit for r in results) == 1
    assert counts(budget) == (1, 1, 1, 0, 0)
    assert len(router.requests) == 1


async def test_guard_refusal_before_the_first_attempt_costs_no_budget() -> None:
    router = Router(ok())
    service, guard = build(router, window_limit=1)
    await guard.before_request(PROVIDER_NAME, "seat_availability")  # another search used it
    budget = SearchBudget(5)
    refused = await service.check(request(), budget=budget)
    assert refused.outcome is SegmentQueryOutcome.QUOTA_EXHAUSTED
    assert counts(budget) == (0, 0, 0, 0, 0)
    assert router.requests == []
    assert await guard_used(guard) == (1, 1)


async def test_guard_refusal_of_a_retry_charges_only_the_attempt_made() -> None:
    router = Router(BUSY, ok())
    service, guard = build(router, window_limit=1)
    budget = SearchBudget(5)
    result = await service.check(request(), budget=budget)
    assert result.outcome is SegmentQueryOutcome.QUOTA_EXHAUSTED
    assert len(router.requests) == 1
    assert counts(budget) == (1, 1, 1, 0, 0)  # the reserved retry unit was returned
    assert await guard_used(guard) == (1, 1)


async def test_checks_outside_a_search_keep_their_retries() -> None:
    """The direct availability endpoint has no search budget; retries work as before."""
    router = Router(BUSY, ok())
    service, guard = build(router)
    assert (await service.check(request())).succeeded
    assert len(router.requests) == 2
    assert await guard_used(guard) == (2, 2)


async def test_adapters_that_do_not_report_attempts_count_one_per_call() -> None:
    provider = MockRailwayProvider(
        failures={
            ("90601", "TIR", "TVC", "3A"): ProviderTimeoutError(
                "slow", provider="MOCK", endpoint="seat_availability"
            )
        }
    )
    store = MemoryStore()
    service = AvailabilityService(
        provider=provider,
        cache=TypedCache(store),
        flight=SingleFlight(store, lock_ttl_seconds=60),
        persistence=InMemoryPersistence(),
        clock=CLOCK,
        ttl_seconds=120,
    )
    budget = SearchBudget(5)
    key = SegmentKey("90601", DAY, "TIR", "TVC", "3A", Quota.GENERAL)
    result = await service.check(SegmentRequest(key, DAY), budget=budget)
    assert result.outcome is SegmentQueryOutcome.PROVIDER_TIMEOUT
    assert counts(budget) == (1, 1, 1, 0, 0)
