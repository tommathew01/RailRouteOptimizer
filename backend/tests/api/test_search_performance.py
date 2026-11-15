"""Guards against event-loop-blocking regressions in search orchestration and planning."""

from __future__ import annotations

import time

import pytest

from app.domain.enums import AvailabilityStatus as S
from app.optimization.planner import ComboSpec, QueryPlanner
from app.optimization.policy import SearchFilters
from app.repositories.memory import InMemoryPersistence
from app.repositories.records import SearchRecord
from app.services.journey_search import JourneySearchService
from tests.api.conftest import api_client, optimize_body
from tests.conftest import make_settings


class CountingPersistence(InMemoryPersistence):
    def __init__(self) -> None:
        super().__init__()
        self.saves = 0

    async def save_search(self, search: SearchRecord) -> None:
        self.saves += 1
        await super().save_search(search)


@pytest.mark.parametrize(("interval", "expect_per_wave"), [(1.0, False), (0.0, True)])
async def test_progress_is_republished_at_most_once_per_interval(
    monkeypatch: pytest.MonkeyPatch, interval: float, expect_per_wave: bool
) -> None:
    monkeypatch.setattr(JourneySearchService, "progress_interval_seconds", interval)
    store = CountingPersistence()
    settings = make_settings(search_max_availability_requests=80, railkit_max_concurrency=2)
    async with api_client(settings, persistence=store) as (client, _):
        body = (
            await client.post("/api/v1/journeys/optimize", json=optimize_body(classes=["3A", "SL"]))
        ).json()
    waves = -(-body["coverage"]["availability_requests_made"] // 2)
    assert waves > 3
    # RUNNING + progress publications + final COMPLETED. The frozen test clock never advances, so
    # with a 1 s interval only the first wave is published.
    if expect_per_wave:
        assert store.saves >= waves + 2  # partial waves can add a few more
    else:
        assert store.saves == 3


def test_planner_worst_case_stays_fast() -> None:
    """Depth-4 exploration that can never be solved, at the maximum per-search budget."""
    destination = 31
    specs = [
        ComboSpec(
            c,
            0,
            destination,
            tuple(range(1, destination)),
            {m: float(m % 7) for m in range(1, destination)},
        )
        for c in range(4)
    ]

    def oracle(edge: tuple[int, int]) -> S:
        if edge == (0, destination):
            return S.WAITLIST
        return S.RAC if edge[1] == destination else S.AVAILABLE

    planner = QueryPlanner(specs, filters=SearchFilters(allow_rac=True))
    started, made, slowest = time.perf_counter(), 0, 0.0
    while not planner.finished and made < 500:
        wave_started = time.perf_counter()
        wave = planner.next_wave(min(4, 500 - made))
        slowest = max(slowest, time.perf_counter() - wave_started)
        if not wave:
            break
        for query in wave:
            planner.record(query, oracle(query.edge))
            made += 1
    planner.stop()
    planner.outstanding_edges()
    assert made == 500
    assert slowest < 0.25  # measured ~8 ms
    assert time.perf_counter() - started < 5.0  # measured ~0.75 s
