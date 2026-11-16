from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.cache.store import MemoryStore, StoreError
from app.core.clock import FrozenClock
from app.providers.base import ProviderRequestEvent
from app.providers.errors import ProviderQuotaExhaustedError
from app.services.quota import ProviderQuotaGuard, QuotaRefusal, SearchBudget

NOW = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)


def guard(
    store: MemoryStore | None = None, clock: FrozenClock | None = None, **kw: int
) -> ProviderQuotaGuard:
    values = {
        "window_limit": 3,
        "window_seconds": 600,
        "monthly_limit": 5,
        "backoff_seconds": 300,
    } | kw
    return ProviderQuotaGuard(store or MemoryStore(), clock=clock or FrozenClock(NOW), **values)


async def refused_reason(g: ProviderQuotaGuard) -> str:
    with pytest.raises(ProviderQuotaExhaustedError) as info:
        await g.before_request("RAILKIT", "seat_availability")
    return str(info.value.diagnostics["reason"])


async def test_window_limit_and_refusals_do_not_consume() -> None:
    g = guard()
    for _ in range(3):
        await g.before_request("RAILKIT", "seat_availability")
    assert await refused_reason(g) == QuotaRefusal.WINDOW
    assert await refused_reason(g) == QuotaRefusal.WINDOW
    snapshot = await g.snapshot("RAILKIT")
    assert (snapshot.window_used, snapshot.monthly_used) == (3, 3)


async def test_window_resets_but_monthly_cap_holds() -> None:
    clock = FrozenClock(NOW)
    g = guard(clock=clock)
    for _ in range(3):
        await g.before_request("RAILKIT", "train_info")
    clock.advance(601)
    for _ in range(2):
        await g.before_request("RAILKIT", "train_info")
    assert await refused_reason(g) == QuotaRefusal.MONTHLY
    assert (await g.snapshot("RAILKIT")).monthly_used == 5


async def test_provider_429_sets_shared_backoff() -> None:
    store = MemoryStore()
    g = guard(store)
    await g.after_request(
        ProviderRequestEvent("RAILKIT", "seat_availability", 1, "RATE_LIMITED", 429, 50.0, 120.0)
    )
    assert await refused_reason(g) == QuotaRefusal.BACKOFF
    other_process = guard(store)  # same store = another worker
    assert await refused_reason(other_process) == QuotaRefusal.BACKOFF


async def test_store_failure_fails_closed() -> None:
    class Down(MemoryStore):
        async def get(self, key: str) -> bytes | None:
            raise StoreError("redis down")

    assert await refused_reason(guard(Down())) == QuotaRefusal.GUARD_UNAVAILABLE


async def test_providers_are_counted_separately() -> None:
    g = guard()
    for _ in range(3):
        await g.before_request("RAILKIT", "x")
    await g.before_request("OTHER", "x")  # not blocked by RAILKIT's window


async def test_search_budget() -> None:
    budget = SearchBudget(2)
    assert await budget.try_consume()
    assert await budget.try_consume()
    assert not await budget.try_consume()
    assert budget.remaining == 0
    await budget.refund()
    assert budget.remaining == 1


async def test_budgeted_call_reserves_first_attempt_and_settles_to_attempts_made() -> None:
    budget = SearchBudget(3)
    call = await budget.start_call()
    assert call is not None
    assert budget.used == 1
    call.attempt_started()
    assert await call.allow_retry()  # reserves a second unit
    call.attempt_started()
    assert budget.used == 2
    assert await call.settle(reached_provider=True) == 2
    assert await call.settle(reached_provider=True) == 2  # idempotent
    assert (budget.used, budget.checks, budget.attempts, budget.retries) == (2, 1, 2, 1)


async def test_unused_reservations_are_returned_and_a_spent_budget_refuses() -> None:
    budget = SearchBudget(2)
    call = await budget.start_call()
    assert call is not None
    assert await call.allow_retry()
    call.attempt_started()  # the retry was then refused by the global guard
    await call.settle(reached_provider=True)
    assert (budget.used, budget.attempts) == (1, 1)
    refused = await budget.start_call()
    assert refused is not None
    await refused.settle(reached_provider=False)  # guard refused the first attempt
    assert (budget.used, budget.checks) == (1, 1)
    assert await budget.start_call() is not None
    assert await budget.start_call() is None
    assert budget.remaining == 0


async def test_unreported_extra_attempts_are_still_charged() -> None:
    """An adapter that retried without asking: accuracy wins over the limit."""
    budget = SearchBudget(1)
    call = await budget.start_call()
    assert call is not None
    for _ in range(3):
        call.attempt_started()
    await call.settle(reached_provider=True)
    assert (budget.used, budget.attempts, budget.retries) == (3, 3, 2)
    assert budget.remaining == 0
