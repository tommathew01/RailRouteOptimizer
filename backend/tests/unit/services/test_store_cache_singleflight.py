from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from pydantic import TypeAdapter

from app.cache import keys
from app.cache.singleflight import SingleFlight
from app.cache.store import MemoryStore, NamespacedStore, StoreError
from app.cache.typed_cache import TypedCache
from app.domain.enums import AvailabilityStatus
from app.domain.models import (
    AvailabilityRecord,
    Fare,
    Prediction,
    PredictionSource,
    SegmentKey,
    SegmentObservation,
    Station,
    TrainRoute,
    TrainStop,
    TrainSummary,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


class SharedStore(MemoryStore):
    """A MemoryStore that claims to be shared, to exercise the distributed lock path."""

    @property
    def distributed(self) -> bool:
        return True


class BrokenStore(MemoryStore):
    async def get(self, key: str) -> bytes | None:
        raise StoreError("down")

    async def set(self, *args: object, **kwargs: object) -> bool:
        raise StoreError("down")


# --- MemoryStore ---------------------------------------------------------------------------------
async def test_memory_store_ttl_nx_incr_and_compare_delete() -> None:
    clock = FakeClock()
    store = MemoryStore(monotonic=clock)
    assert await store.set("a", b"1", ttl_seconds=10)
    assert not await store.set("a", b"2", only_if_absent=True)
    assert await store.get("a") == b"1"
    clock.t += 11
    assert await store.get("a") is None
    assert await store.incr("n", ttl_seconds=5) == 1
    assert await store.incr("n", ttl_seconds=5) == 2
    assert await store.ttl("n") == pytest.approx(5)
    clock.t += 6
    assert await store.incr("n") == 1  # expired window starts again
    await store.set("lock", b"token-a")
    assert not await store.delete_if_equals("lock", b"token-b")
    assert await store.delete_if_equals("lock", b"token-a")


async def test_namespaced_store_isolates_environments() -> None:
    inner = MemoryStore()
    prod, dev = (
        NamespacedStore(inner, "railroute:production:"),
        NamespacedStore(inner, "railroute:dev:"),
    )
    await prod.set("k", b"p")
    assert await dev.get("k") is None
    assert await inner.get("railroute:production:k") == b"p"


# --- Keys ----------------------------------------------------------------------------------------
def test_availability_key_includes_provider_and_both_dates() -> None:
    key = SegmentKey("12345", date(2026, 11, 20), "TIR", "SRR", "3A")
    assert keys.availability("RAILKIT", key, date(2026, 11, 21)) == (
        "availability:RAILKIT:12345:2026-11-20:2026-11-21:TIR:SRR:3A:GN"
    )
    assert keys.station_search("MOCK", "  Tirur   Jn ") == "station-search:MOCK:tirur jn"


# --- TypedCache round trips ---------------------------------------------------------------
OBSERVATION = SegmentObservation(
    id=uuid.uuid4(),
    key=SegmentKey("12345", date(2026, 11, 20), "TIR", "SRR", "3A"),
    provider_date=date(2026, 11, 20),
    record=AvailabilityRecord(
        status=AvailabilityStatus.WAITLIST,
        provider="RAILKIT",
        raw_status="RLWL31/WL23",
        waitlist_type="RLWL",
        waitlist_number=23,
        can_book=True,
        prediction=Prediction("RAILKIT", "73% Chance", 73.0, PredictionSource.FIELD),
        fare=Fare(Decimal("1670.00"), "INR", "X"),
        anomalies=("ECHO_MISSING:quota",),
        raw_payload={"availability": [{"rawStatus": "RLWL31/WL23"}]},
    ),
    observed_at=datetime(2026, 11, 8, 10, 0, tzinfo=UTC),
)
ROUTE = TrainRoute(
    "12345",
    "TEST",
    (TrainStop(0, "TIR", "Tirur", None, time(21, 5), 0, 0, 0.0, "1", True),),
    "RAILKIT",
    datetime(2026, 11, 8, tzinfo=UTC),
    classes=("3A", "SL"),
)


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (OBSERVATION, SegmentObservation),
        (ROUTE, TrainRoute),
        (
            [TrainSummary("12345", "X", "TIR", "TVC", departure_time=time(21, 5))],
            list[TrainSummary],
        ),
        ([Station("TIR", "Tirur", None, 10.9, 75.9)], list[Station]),
    ],
)
async def test_typed_cache_round_trips_domain_types(value: object, kind: object) -> None:
    cache = TypedCache(MemoryStore())
    adapter: TypeAdapter[object] = TypeAdapter(kind)  # type: ignore[arg-type]
    await cache.set("k", value, adapter, ttl_seconds=60)
    assert await cache.get("k", adapter) == value


async def test_corrupt_entries_are_discarded_and_store_errors_are_misses() -> None:
    store = MemoryStore()
    cache = TypedCache(store)
    await store.set("k", b"{not json")
    assert await cache.get("k", TypeAdapter(TrainRoute)) is None
    assert await store.get("k") is None
    broken = TypedCache(BrokenStore())
    assert await broken.get("k", TypeAdapter(int)) is None
    await broken.set("k", 1, TypeAdapter(int), ttl_seconds=10)  # logged, not raised


async def test_zero_ttl_disables_caching() -> None:
    store = MemoryStore()
    await TypedCache(store).set("k", 1, TypeAdapter(int), ttl_seconds=0)
    assert await store.get("k") is None


# --- SingleFlight ----------------------------------------------------------------------------
async def test_in_process_duplicates_share_one_computation() -> None:
    calls = 0

    async def compute() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return "value"

    async def load_cached() -> str | None:
        return None

    flight = SingleFlight(MemoryStore(), lock_ttl_seconds=5)
    results = await asyncio.gather(
        *(flight.run("k", compute=compute, load_cached=load_cached) for _ in range(10))
    )
    assert calls == 1
    assert [value for value, _ in results] == ["value"] * 10
    assert sum(shared for _, shared in results) == 9


async def test_errors_propagate_to_every_waiter_and_are_not_cached() -> None:
    async def compute() -> str:
        await asyncio.sleep(0.01)
        raise RuntimeError("provider down")

    async def load_cached() -> str | None:
        return None

    flight = SingleFlight(MemoryStore(), lock_ttl_seconds=5)
    results = await asyncio.gather(
        *(flight.run("k", compute=compute, load_cached=load_cached) for _ in range(3)),
        return_exceptions=True,
    )
    assert all(isinstance(r, RuntimeError) for r in results)
    later = await flight.run("k", compute=lambda: asyncio.sleep(0, "ok"), load_cached=load_cached)
    assert later == ("ok", False)


async def test_distributed_lock_makes_second_process_wait_for_cache() -> None:
    store = SharedStore()
    cache: dict[str, str] = {}
    calls = 0

    async def compute() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        cache["k"] = "fresh"
        return "fresh"

    async def load_cached() -> str | None:
        return cache.get("k")

    process_a = SingleFlight(store, lock_ttl_seconds=5, poll_interval_seconds=0.01)
    process_b = SingleFlight(store, lock_ttl_seconds=5, poll_interval_seconds=0.01)
    (a, a_shared), (b, b_shared) = await asyncio.gather(
        process_a.run("k", compute=compute, load_cached=load_cached),
        process_b.run("k", compute=compute, load_cached=load_cached),
    )
    assert calls == 1
    assert a == b == "fresh"
    assert a_shared != b_shared
    assert await store.get("lock:k") is None  # released


async def test_lock_wait_timeout_falls_back_to_computing() -> None:
    store = SharedStore()
    await store.set("lock:k", b"someone-else", ttl_seconds=60)

    async def load_cached() -> str | None:
        return None

    flight = SingleFlight(
        store, lock_ttl_seconds=60, wait_timeout_seconds=0.05, poll_interval_seconds=0.01
    )
    value = await flight.run("k", compute=lambda: asyncio.sleep(0, "mine"), load_cached=load_cached)
    assert value == ("mine", False)
