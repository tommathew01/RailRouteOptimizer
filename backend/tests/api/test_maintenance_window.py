"""The IRCTC maintenance window through the public API (docs/08 D-31). Mock provider.

Every route that could make a train or availability request is refused with 503 and spends
nothing; stored results, stations and metadata stay available.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import pytest

from app.core.clock import FrozenClock
from app.domain.time import IST
from app.providers.mock.provider import MockRailwayProvider
from tests.api.conftest import JOURNEY_DATE, api_client, optimize_body
from tests.conftest import make_settings

INSIDE = datetime(2026, 11, 16, 23, 50, tzinfo=IST)
JUST_BEFORE = datetime(2026, 11, 16, 23, 44, 59, tzinfo=IST)
REOPENED = datetime(2026, 11, 17, 0, 20, tzinfo=IST)
DATE = (JOURNEY_DATE - timedelta(days=1)).isoformat()  # inside the booking horizon of 16 Nov

RAILWAY_CALLS: list[tuple[str, str, dict[str, Any] | None]] = [
    (
        "POST",
        "/api/v1/trains/search",
        {"source": "TIR", "destination": "TVC", "journey_date": DATE},
    ),
    ("GET", "/api/v1/trains/90601/route", None),
    ("POST", "/api/v1/journeys/optimize", optimize_body(journey_date=DATE)),
    ("POST", "/api/v1/journeys/preview", optimize_body(journey_date=DATE)),
    (
        "POST",
        "/api/v1/availability/check",
        {
            "train_number": "90601",
            "source": "TIR",
            "destination": "TVC",
            "journey_date": DATE,
            "travel_class": "3A",
        },
    ),
]


@pytest.mark.parametrize(("method", "path", "body"), RAILWAY_CALLS)
async def test_railway_requests_are_refused_inside_the_window(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    provider = MockRailwayProvider()
    async with api_client(provider=provider, clock=FrozenClock(INSIDE)) as (client, _):
        response = await client.request(method, path, json=body)
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "RAILWAY_MAINTENANCE"
    assert "11:45 PM and 12:20 AM IST" in error["message"]
    assert error["details"]["available_at"] == REOPENED.isoformat()
    assert response.headers["retry-after"] == str(30 * 60)  # 23:50 → 00:20
    assert provider.calls == Counter()  # nothing reached the provider


@pytest.mark.parametrize("moment", [JUST_BEFORE, REOPENED])
async def test_railway_requests_work_outside_the_window(moment: datetime) -> None:
    async with api_client(clock=FrozenClock(moment)) as (client, _):
        for method, path, body in RAILWAY_CALLS:
            response = await client.request(method, path, json=body)
            assert response.status_code in (200, 202), (path, response.text)


async def test_stored_results_stations_and_meta_stay_available() -> None:
    clock = FrozenClock(JUST_BEFORE - timedelta(minutes=5))
    async with api_client(clock=clock) as (client, _):
        done = (
            await client.post("/api/v1/journeys/optimize", json=optimize_body(journey_date=DATE))
        ).json()
        clock.advance(10 * 60)  # now 23:49:59 IST
        stored = await client.get(f"/api/v1/journeys/{done['search_id']}")
        stations = await client.get("/api/v1/stations/search", params={"q": "Tirur"})
        meta = (await client.get("/api/v1/meta")).json()
    assert stored.status_code == 200
    assert stored.json()["recommendations"] == done["recommendations"]
    assert stations.status_code == 200
    assert meta["railway_maintenance"] == {
        "enabled": True,
        "starts_at": "23:45",
        "ends_at": "00:20",
        "timezone": "Asia/Kolkata",
        "message": meta["railway_maintenance"]["message"],
    }


async def test_a_search_running_into_the_window_stops_sending_requests() -> None:
    class CrossingClock(FrozenClock):
        """Each provider call takes 2 s of wall-clock time."""

    clock = CrossingClock(datetime(2026, 11, 16, 23, 44, 50, tzinfo=IST))
    provider = MockRailwayProvider()
    original = provider.get_availability

    async def slow(query: Any) -> Any:
        clock.advance(2)
        return await original(query)

    provider.get_availability = slow  # type: ignore[method-assign]
    settings = make_settings(search_max_availability_requests=200, railkit_max_concurrency=1)
    async with api_client(settings, provider=provider, clock=clock) as (client, _):
        body = (
            await client.post("/api/v1/journeys/optimize", json=optimize_body(journey_date=DATE))
        ).json()
    made = body["coverage"]["availability_requests_made"]
    assert 0 < made <= 6  # 23:44:50 + 2 s per call: no call starts at or after 23:45
    assert body["incomplete_reason"] == "RAILWAY_MAINTENANCE_WINDOW"
    assert any("maintenance window" in w for w in body["warnings"])


async def test_the_window_can_be_disabled_for_testing() -> None:
    settings = make_settings(railway_maintenance_enabled=False)
    async with api_client(settings, clock=FrozenClock(INSIDE)) as (client, _):
        response = await client.post(
            "/api/v1/journeys/optimize", json=optimize_body(journey_date=DATE)
        )
        meta = (await client.get("/api/v1/meta")).json()
    assert response.status_code == 200
    assert meta["railway_maintenance"]["enabled"] is False
