"""Stop search through the public API, with real background execution (docs/08 D-35).

A gated mock provider pauses at chosen points so the stop arrives at a known moment. Asserted
throughout: no availability request starts after the stop, results already found are kept,
the snapshot says the search was stopped, and other searches are unaffected.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from app.domain.models import AvailabilityQuery, AvailabilityRecord, TrainSummary
from app.providers.mock.provider import MockRailwayProvider
from tests.api.conftest import api_client, container_of, optimize_body
from tests.conftest import make_settings

ASYNC = {"search_execution_mode": "async", "railkit_max_concurrency": 4}


class GatedProvider(MockRailwayProvider):
    """Availability calls after the first ``free`` ones wait for ``release``; the train search
    waits for ``discovery`` when ``hold_discovery`` is set."""

    def __init__(self, *, free: int = 10_000, hold_discovery: bool = False) -> None:
        super().__init__()
        self.free = free
        self.started = 0
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()
        self.hold_discovery = hold_discovery
        self.discovering = asyncio.Event()
        self.discovery = asyncio.Event()

    async def search_trains(self, *args: Any, **kwargs: Any) -> list[TrainSummary]:
        if self.hold_discovery:
            self.discovering.set()
            await self.discovery.wait()
        return await super().search_trains(*args, **kwargs)

    async def get_availability(self, query: AvailabilityQuery) -> AvailabilityRecord:
        self.started += 1
        if self.started > self.free:
            self.blocked.set()
            await self.release.wait()
        return await super().get_availability(query)


async def start(client: Any, **body: Any) -> str:
    response = await client.post("/api/v1/journeys/optimize", json=optimize_body(**body))
    assert response.status_code == 202, response.text
    search_id: str = response.json()["search_id"]
    return search_id


async def result(client: Any, search_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/v1/journeys/{search_id}")).json()
    return body


async def test_stop_mid_search_sends_nothing_new_and_keeps_what_was_found() -> None:
    provider = GatedProvider(free=4)  # the first wave answers; the second is in flight
    settings = make_settings(search_max_availability_requests=200, **ASYNC)
    async with api_client(settings, provider=provider) as (client, app):
        search_id = await start(client)
        await asyncio.wait_for(provider.blocked.wait(), 5)
        await asyncio.sleep(0.05)  # let the rest of the wave start too
        sent_before_stop = provider.started

        stop = await client.post(f"/api/v1/journeys/{search_id}/stop")
        assert stop.status_code == 202
        assert stop.json()["stop_requested"] is True
        provider.release.set()  # requests already sent finish normally
        await container_of(app).executor.wait_idle()  # type: ignore[attr-defined]
        body = await result(client, search_id)

    assert provider.started == sent_before_stop  # not one request after the stop
    assert body["status"] == "COMPLETED"
    assert body["search_completeness"] in ("PARTIAL_STOPPED", "NO_PATH_FOUND_PARTIAL")
    assert body["incomplete_reason"] == "STOPPED_BY_USER"
    coverage = body["coverage"]
    assert coverage["availability_requests_made"] == sent_before_stop
    assert coverage["segments_checked"] + coverage["segments_unknown"] == sent_before_stop
    assert any("You stopped the search" in w for w in body["warnings"])
    assert len(body["recommendations"]) <= 10


async def test_stop_right_after_starting_sends_no_availability_request() -> None:
    provider = GatedProvider(hold_discovery=True)
    async with api_client(make_settings(**ASYNC), provider=provider) as (client, app):
        search_id = await start(client)
        await asyncio.wait_for(provider.discovering.wait(), 5)
        assert (await client.post(f"/api/v1/journeys/{search_id}/stop")).status_code == 202
        provider.discovery.set()
        await container_of(app).executor.wait_idle()  # type: ignore[attr-defined]
        body = await result(client, search_id)

    assert provider.availability_queries == []
    assert body["search_completeness"] == "NO_PATH_FOUND_PARTIAL"
    assert body["incomplete_reason"] == "STOPPED_BY_USER"
    assert body["recommendations"] == []


async def test_a_queued_search_stopped_before_it_runs_asks_nothing_and_others_finish() -> None:
    """One executor slot: search A runs (held at discovery), B waits in the queue and is
    stopped. B asks the provider nothing at all; A — another user — completes normally."""
    provider = GatedProvider(hold_discovery=True)
    settings = make_settings(max_concurrent_searches=1, **ASYNC)
    async with api_client(settings, provider=provider) as (client, app):
        first = await start(client)
        await asyncio.wait_for(provider.discovering.wait(), 5)
        second = await start(client, classes=["SL"])
        assert (await client.post(f"/api/v1/journeys/{second}/stop")).status_code == 202
        provider.discovery.set()
        await container_of(app).executor.wait_idle()  # type: ignore[attr-defined]
        a, b = await result(client, first), await result(client, second)

    assert a["incomplete_reason"] != "STOPPED_BY_USER"
    assert a["search_completeness"] not in ("PARTIAL_STOPPED",)
    assert {q.travel_class for q in provider.availability_queries} == {"3A"}  # only A asked
    assert provider.calls["train_search"] == 1  # B did not even look up trains
    assert b["incomplete_reason"] == "STOPPED_BY_USER"
    assert b["coverage"]["availability_requests_made"] == 0


async def test_stopping_twice_is_harmless_and_a_finished_search_cannot_be_stopped() -> None:
    provider = GatedProvider(free=4)
    settings = make_settings(search_max_availability_requests=200, **ASYNC)
    async with api_client(settings, provider=provider) as (client, app):
        search_id = await start(client)
        await asyncio.wait_for(provider.blocked.wait(), 5)
        first = await client.post(f"/api/v1/journeys/{search_id}/stop")
        second = await client.post(f"/api/v1/journeys/{search_id}/stop")
        provider.release.set()
        await container_of(app).executor.wait_idle()  # type: ignore[attr-defined]
        stopped = await result(client, search_id)
        after = await client.post(f"/api/v1/journeys/{search_id}/stop")
        unchanged = await result(client, search_id)

    assert (first.status_code, second.status_code) == (202, 202)
    assert after.status_code == 200
    assert after.json()["stop_requested"] is False
    assert after.json()["status"] == "COMPLETED"
    assert unchanged == stopped  # a stop after completion changes nothing


async def test_a_new_search_after_a_stop_starts_clean() -> None:
    provider = GatedProvider(free=4)
    settings = make_settings(search_max_availability_requests=200, **ASYNC)
    async with api_client(settings, provider=provider) as (client, app):
        stopped_id = await start(client)
        await asyncio.wait_for(provider.blocked.wait(), 5)
        await client.post(f"/api/v1/journeys/{stopped_id}/stop")
        provider.release.set()
        await container_of(app).executor.wait_idle()  # type: ignore[attr-defined]

        again_id = await start(client)  # "Check again": a new search with a new id
        await container_of(app).executor.wait_idle()  # type: ignore[attr-defined]
        again = await result(client, again_id)

    assert again_id != stopped_id
    assert again["incomplete_reason"] != "STOPPED_BY_USER"
    assert again["search_completeness"] != "PARTIAL_STOPPED"
    assert again["coverage"]["cache_hits"] > 0  # answers fetched before the stop are reused


async def test_stopping_an_unknown_search_is_404() -> None:
    async with api_client() as (client, _):
        response = await client.post("/api/v1/journeys/00000000-0000-4000-8000-000000000000/stop")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SEARCH_NOT_FOUND"


async def test_completed_searches_show_the_top_ten_of_the_existing_ranking() -> None:
    """The limit is applied after ranking everything found: the 10 shown are exactly the
    first 10 of the full ranking (same order, same metadata)."""
    body = optimize_body(classes=["3A", "SL"], filters={"allow_rac": True, "allow_waitlist": True})
    async with api_client(make_settings(search_max_availability_requests=300)) as (client, _):
        top = (await client.post("/api/v1/journeys/optimize", json=body)).json()
    settings = make_settings(search_max_availability_requests=300, max_recommendations=100)
    async with api_client(settings) as (client, _):
        everything = (await client.post("/api/v1/journeys/optimize", json=body)).json()

    def comparable(recs: list[dict[str, Any]]) -> list[Any]:
        return [
            {k: v for k, v in r.items() if k != "segments"}
            | {
                "segments": [
                    {k: v for k, v in s.items() if k != "observation_id"} for s in r["segments"]
                ]
            }
            for r in recs
        ]

    assert len(everything["recommendations"]) > 10
    assert len(top["recommendations"]) == 10
    assert [r["rank"] for r in top["recommendations"]] == list(range(1, 11))
    assert comparable(top["recommendations"]) == comparable(everything["recommendations"][:10])
    assert Counter(r["quota"] for r in top["recommendations"]) == Counter(
        r["quota"] for r in everything["recommendations"][:10]
    )
