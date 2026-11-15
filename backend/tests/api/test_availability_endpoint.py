from __future__ import annotations

import httpx
import pytest

from app.domain.models import AvailabilityQuery, AvailabilityRecord
from app.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from app.providers.mock.provider import MockRailwayProvider
from tests.api.conftest import JOURNEY_DATE, api_client


def body(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "train_number": "90601",
        "source": "TIR",
        "destination": "TVC",
        "journey_date": JOURNEY_DATE.isoformat(),
        "travel_class": "3A",
    }
    payload.update(overrides)
    return payload


async def test_check_reports_status_and_prediction_separately(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/availability/check", json=body())
    assert response.status_code == 200
    data = response.json()
    assert data["quota"] == "GN"
    assert data["availability"]["status"] == "WAITLIST"
    assert data["availability"]["raw_status"] == "GNWL42/WL27"
    assert data["prediction"] == {
        "provider": "MOCK",
        "label": "Demo estimate",
        "text": "38% Chance",
        "percentage": 38.0,
        "percentage_source": "FIELD",
    }
    assert data["provider_checked_at"] is None
    assert data["cached"] is False
    assert data["data_mode"] == "DEMO"
    again = (await client.post("/api/v1/availability/check", json=body())).json()
    assert again["cached"] is True


async def test_client_quota_is_ignored_and_gn_enforced() -> None:
    provider = MockRailwayProvider()
    async with api_client(provider=provider) as (client, _):
        response = await client.post("/api/v1/availability/check", json=body(quota="TQ"))
    assert response.status_code == 200
    assert response.json()["quota"] == "GN"
    assert provider.availability_queries[0].quota.value == "GN"
    assert any("quota was ignored" in w for w in response.json()["warnings"])


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"source": "TVC", "destination": "TIR"}, 422, "INVALID_SEGMENT"),
        ({"source": "TIR", "destination": "MAS"}, 422, "INVALID_SEGMENT"),
        ({"travel_class": "1A"}, 422, "CLASS_NOT_OFFERED"),
        ({"travel_class": "VS"}, 422, "UNSUPPORTED_CLASS"),
        ({"train_number": "1234"}, 400, "INVALID_REQUEST"),
    ],
)
async def test_semantic_validation(
    client: httpx.AsyncClient, overrides: dict[str, object], status: int, code: str
) -> None:
    response = await client.post("/api/v1/availability/check", json=body(**overrides))
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


class FailingProvider(MockRailwayProvider):
    def __init__(self, error: ProviderError) -> None:
        super().__init__()
        self.error = error

    async def get_availability(self, query: AvailabilityQuery) -> AvailabilityRecord:
        raise self.error


def _err(cls: type[ProviderError], **kw: object) -> ProviderError:
    return cls("secret-free message", provider="MOCK", endpoint="seat_availability", **kw)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (_err(ProviderAuthError, status_code=401), 503, "PROVIDER_UNAVAILABLE"),
        (
            _err(ProviderRateLimitedError, status_code=429, retry_after_seconds=30),
            429,
            "PROVIDER_RATE_LIMITED",
        ),
        (_err(ProviderTimeoutError), 504, "PROVIDER_TIMEOUT"),
        (_err(ProviderInvalidResponseError), 502, "PROVIDER_INVALID_RESPONSE"),
        (_err(ProviderUpstreamError, status_code=503), 502, "PROVIDER_UPSTREAM_ERROR"),
    ],
)
async def test_provider_failures_map_to_documented_statuses(
    error: ProviderError, status: int, code: str
) -> None:
    async with api_client(provider=FailingProvider(error)) as (client, application):
        response = await client.post("/api/v1/availability/check", json=body())
        runs = application.state.container.persistence.segment_runs
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert runs[0].outcome.value != "SUCCESS"  # the failed attempt is recorded, not hidden
    if status == 429:
        assert response.headers["retry-after"] == "30"
