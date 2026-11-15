from __future__ import annotations

import logging

import httpx
import pytest

from app.core.clock import FrozenClock
from app.integrations.railkit.client import RailKitHttpClient
from app.integrations.railkit.provider import RailKitProvider
from app.repositories.memory import InMemoryPersistence
from tests.api.conftest import NOW, api_client, optimize_body
from tests.conftest import make_settings
from tests.unit.providers.railkit_helpers import Router, json_response

API_KEY = "rk_live_must_never_leak_42"


async def test_metrics_open_in_test_environment_without_token() -> None:
    async with api_client() as (client, _):
        await client.post("/api/v1/journeys/optimize", json=optimize_body())
        response = await client.get("/api/v1/metrics")
    assert response.status_code == 200
    assert "railroute_searches_total" in response.text


async def test_metrics_require_token_when_configured() -> None:
    async with api_client(make_settings(metrics_token="ops-token-123456")) as (client, _):
        anonymous = await client.get("/api/v1/metrics")
        wrong = await client.get("/api/v1/metrics", headers={"Authorization": "Bearer nope"})
        right = await client.get(
            "/api/v1/metrics", headers={"Authorization": "Bearer ops-token-123456"}
        )
        quota = await client.get(
            "/api/v1/ops/provider-quota", headers={"Authorization": "Bearer ops-token-123456"}
        )
    assert anonymous.status_code == 401
    assert wrong.status_code == 401
    assert right.status_code == 200
    assert quota.json()["monthly_limit"] == 50


async def test_metrics_disabled_outside_dev_without_token() -> None:
    staging = make_settings(environment="staging")
    async with api_client(staging, persistence=InMemoryPersistence()) as (client, _):
        assert (await client.get("/api/v1/metrics")).status_code == 404


def railkit_provider(router: Router) -> RailKitProvider:
    client = RailKitHttpClient(
        base_url="https://api.railkit.test",
        api_key=API_KEY,
        timeout=httpx.Timeout(1.0),
        max_retries=0,
        transport=router.transport,
    )
    return RailKitProvider(
        client, clock=FrozenClock(NOW), fare_currency="INR", secret_fragments=[API_KEY]
    )


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_railkit_key_never_reaches_clients_or_logs(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    router = Router(
        json_response(status, {"success": False, "error": f"Invalid API key {API_KEY}"})
    )
    settings = make_settings(railway_provider="railkit", railkit_api_key=API_KEY)
    async with api_client(settings, provider=railkit_provider(router)) as (client, _):
        responses = [
            await client.post(
                "/api/v1/trains/search",
                json={"source": "TIR", "destination": "TVC", "journey_date": "2026-11-20"},
            ),
            await client.post("/api/v1/journeys/optimize", json=optimize_body()),
            await client.get("/api/v1/meta"),
        ]
    for response in responses:
        assert API_KEY not in response.text
        assert "x-api-key" not in response.text.lower()
    assert responses[0].status_code in (429, 502, 503)
    assert router.requests[0].headers["x-api-key"] == API_KEY  # sent to the provider only
    assert API_KEY not in caplog.text


async def test_live_mode_is_labelled_live() -> None:
    router = Router(json_response(200, {"success": True, "data": {"stations": []}}))
    settings = make_settings(railway_provider="railkit", railkit_api_key=API_KEY)
    async with api_client(settings, provider=railkit_provider(router)) as (client, _):
        meta = (await client.get("/api/v1/meta")).json()
    assert meta["data_mode"] == "LIVE"
    assert not any("Demo mode" in d for d in meta["disclaimers"])
