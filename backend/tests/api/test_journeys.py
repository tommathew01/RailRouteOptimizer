from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.domain.enums import SearchStatus
from app.domain.models import TrainSummary
from app.providers.errors import ProviderAuthError, ProviderTimeoutError
from app.providers.mock.provider import MockRailwayProvider
from app.repositories.memory import InMemoryPersistence
from app.services.executor import InProcessExecutor
from tests.api.conftest import NOW, api_client, container_of, optimize_body
from tests.conftest import make_settings


async def test_sync_search_completes_with_ranked_same_train_recommendations() -> None:
    async with api_client(make_settings(search_max_availability_requests=60)) as (client, _):
        response = await client.post("/api/v1/journeys/optimize", json=optimize_body())
        assert response.status_code == 200
        body = response.json()
        fetched = (await client.get(body["status_url"])).json()
    assert body["status"] == "COMPLETED"
    assert body["data_mode"] == "DEMO"
    assert body["request"]["quota"] == "GN"
    best = body["recommendations"][0]
    assert best["rank"] == 1
    assert best["status_tier"] == 0
    assert [s["source"] for s in best["segments"]] == ["TIR", "ERS"]
    assert best["segments"][-1]["destination"] == "TVC"
    assert {s["observation_id"] for s in best["segments"]}  # traceable to stored observations
    for rec in body["recommendations"]:
        assert 1 <= rec["segment_count"] <= 4
        assert rec["quota"] == "GN"
        stations = [rec["segments"][0]["source"]] + [s["destination"] for s in rec["segments"]]
        assert stations[0] == "TIR"
        assert stations[-1] == "TVC"
        assert all(
            a["destination"] == b["source"]
            for a, b in zip(rec["segments"], rec["segments"][1:], strict=False)
        )
    assert any("separate reservation" in w for w in body["warnings"])
    assert fetched["recommendations"] == body["recommendations"]


async def test_async_search_returns_202_then_polls_to_completion() -> None:
    settings = make_settings(search_execution_mode="async")
    async with api_client(settings) as (client, application):
        response = await client.post("/api/v1/journeys/optimize", json=optimize_body())
        assert response.status_code == 202
        accepted = response.json()
        assert response.headers["location"] == accepted["status_url"]
        assert accepted["status"] in ("QUEUED", "RUNNING")
        executor = container_of(application).executor
        assert isinstance(executor, InProcessExecutor)
        await executor.wait_idle()
        final = (await client.get(accepted["status_url"])).json()
    assert final["status"] == "COMPLETED"
    assert final["coverage"]["availability_requests_made"] > 0


async def test_budget_exhaustion_is_partial_and_explained() -> None:
    async with api_client(make_settings(search_max_availability_requests=3)) as (client, _):
        body = (
            await client.post("/api/v1/journeys/optimize", json=optimize_body(classes=["3A", "SL"]))
        ).json()
    assert body["search_completeness"] in ("PARTIAL_BUDGET", "NO_PATH_FOUND_PARTIAL")
    assert body["incomplete_reason"] == "AVAILABILITY_REQUEST_BUDGET_REACHED"
    assert body["coverage"]["availability_requests_made"] == 3
    assert body["coverage"]["availability_requests_planned"] > 3
    assert any("budget" in w for w in body["warnings"])


async def test_failed_segments_are_unknown_not_unavailable() -> None:
    timeout = ProviderTimeoutError("slow", provider="MOCK", endpoint="seat_availability")
    provider = MockRailwayProvider(failures={("90601", "ERS", "TVC", "3A"): timeout})
    async with api_client(
        make_settings(search_max_availability_requests=80), provider=provider
    ) as (client, _):
        body = (
            await client.post(
                "/api/v1/journeys/optimize", json=optimize_body(train_numbers=["90601"])
            )
        ).json()
    assert body["search_completeness"] in ("PARTIAL_PROVIDER_ERRORS", "NO_PATH_FOUND_PARTIAL")
    assert body["coverage"]["segments_failed"] >= 1
    for rec in body["recommendations"]:
        assert ("ERS", "TVC") not in {(s["source"], s["destination"]) for s in rec["segments"]}
        assert all(s["status"] not in ("UNKNOWN", "NOT_AVAILABLE") for s in rec["segments"])


async def test_train_discovery_failure_fails_search_cleanly() -> None:
    class NoTrains(MockRailwayProvider):
        async def search_trains(self, *args: object) -> list[TrainSummary]:
            raise ProviderAuthError("bad key", provider="MOCK", endpoint="train_search")

    async with api_client(provider=NoTrains()) as (client, _):
        body = (await client.post("/api/v1/journeys/optimize", json=optimize_body())).json()
    assert body["status"] == "FAILED"
    assert body["error"]["code"] == "PROVIDER_UNAVAILABLE"


async def test_train_selection_and_unknown_trains_are_reported() -> None:
    async with api_client() as (client, _):
        body = (
            await client.post(
                "/api/v1/journeys/optimize", json=optimize_body(train_numbers=["90603", "11111"])
            )
        ).json()
    evaluations = {t["train_number"]: t["evaluation"] for t in body["trains"]}
    assert evaluations == {"90603": "EVALUATED", "11111": "NOT_IN_TRAIN_SEARCH"}
    assert all(r["train_number"] == "90603" for r in body["recommendations"])


async def test_class_not_offered_by_train_is_skipped_without_spending_budget() -> None:
    provider = MockRailwayProvider()
    async with api_client(provider=provider) as (client, _):
        body = (
            await client.post(
                "/api/v1/journeys/optimize",
                json=optimize_body(classes=["1A"], train_numbers=["90601"]),
            )
        ).json()
    [train] = body["trains"]
    assert train["classes"][0]["state"] == "NOT_OFFERED"
    assert provider.calls["seat_availability"] == 0


async def test_policy_clamps_and_notes() -> None:
    async with api_client() as (client, _):
        body = (
            await client.post(
                "/api/v1/journeys/optimize", json=optimize_body(max_segments=7, quota="TQ")
            )
        ).json()
    assert body["request"]["max_segments"] == 4
    assert any("reduced to the server limit" in w for w in body["warnings"])
    assert any("quota was ignored" in w for w in body["warnings"])


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"classes": ["XX"]}, 422, "UNSUPPORTED_CLASS"),
        ({"classes": []}, 400, "INVALID_REQUEST"),
        ({"journey_date": "2026-01-01"}, 400, "INVALID_JOURNEY_DATE"),
        ({"destination": "TIR"}, 422, "INVALID_JOURNEY"),
        ({"max_segments": 0}, 400, "INVALID_REQUEST"),
        ({"passenger_count": 2}, 400, "INVALID_REQUEST"),
        ({"train_numbers": [f"9060{i}" for i in range(7)]}, 400, "TOO_MANY_TRAINS"),
    ],
)
async def test_optimize_validation(overrides: dict[str, object], status: int, code: str) -> None:
    async with api_client() as (client, _):
        response = await client.post("/api/v1/journeys/optimize", json=optimize_body(**overrides))
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_repeated_search_reuses_cached_observations() -> None:
    provider = MockRailwayProvider()
    async with api_client(provider=provider) as (client, _):
        first = (await client.post("/api/v1/journeys/optimize", json=optimize_body())).json()
        calls_after_first = provider.calls["seat_availability"]
        second = (await client.post("/api/v1/journeys/optimize", json=optimize_body())).json()
    assert provider.calls["seat_availability"] == calls_after_first
    assert second["coverage"]["availability_requests_made"] == 0
    assert second["coverage"]["cache_hits"] == first["coverage"]["availability_requests_made"]
    assert second["recommendations"][0]["segments"][0]["cached"] is True


async def test_unknown_search_is_404() -> None:
    async with api_client() as (client, _):
        response = await client.get(f"/api/v1/journeys/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SEARCH_NOT_FOUND"


async def test_search_endpoints_are_rate_limited() -> None:
    async with api_client(make_settings(api_rate_limit_search_requests=2)) as (client, _):
        codes = [
            (await client.post("/api/v1/journeys/optimize", json=optimize_body())).status_code
            for _ in range(3)
        ]
        limited = await client.post("/api/v1/journeys/optimize", json=optimize_body())
    assert codes[:2] == [200, 200]
    assert codes[2] == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited.headers["retry-after"]) >= 1


async def test_recommendations_are_persisted_for_audit() -> None:
    async with api_client() as (client, application):
        body = (await client.post("/api/v1/journeys/optimize", json=optimize_body())).json()
        store = container_of(application).persistence
    assert len(store.recommendations) == len(body["recommendations"])  # type: ignore[attr-defined]
    assert store.segment_runs  # type: ignore[attr-defined]
    ids = {seg.observation_id for rec in store.recommendations for seg in rec.segments}  # type: ignore[attr-defined]
    assert ids <= set(store.observations)  # type: ignore[attr-defined]


@pytest.mark.parametrize(("minutes_since_update", "expected"), [(60, "FAILED"), (1, "RUNNING")])
async def test_abandoned_searches_are_reaped_lazily(
    minutes_since_update: int, expected: str
) -> None:
    store = InMemoryPersistence()
    async with api_client(persistence=store) as (client, _):
        body = (await client.post("/api/v1/journeys/optimize", json=optimize_body())).json()
        record = store.searches[uuid.UUID(body["search_id"])]
        record.status = SearchStatus.RUNNING  # as if its process died mid-search
        record.updated_at = NOW - timedelta(minutes=minutes_since_update)
        polled = (await client.get(body["status_url"])).json()
    assert polled["status"] == expected
    assert polled["recommendations"] == body["recommendations"]  # partial results are kept
    if expected == "FAILED":
        assert polled["error"]["code"] == "INTERRUPTED"


@pytest.mark.parametrize(
    ("policy", "warned"), [("SEGMENT_BOARDING_DATE", False), ("TRAIN_START_DATE", True)]
)
async def test_after_midnight_warning_only_for_the_unverified_date_policy(
    policy: str, warned: bool
) -> None:
    settings = make_settings(availability_date_policy=policy, search_max_availability_requests=60)
    async with api_client(settings) as (client, _):
        meta = (await client.get("/api/v1/meta")).json()
        body = (await client.post("/api/v1/journeys/optimize", json=optimize_body())).json()
    assert meta["availability_date_policy_verified"] is not warned
    assert any(s["boards_on_later_date"] for r in body["recommendations"] for s in r["segments"])
    assert any("after midnight" in w for w in body["warnings"]) is warned
