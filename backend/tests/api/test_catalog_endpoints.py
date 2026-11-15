from __future__ import annotations

import httpx
import pytest

from app.domain.models import Station
from app.providers.errors import ProviderTimeoutError
from app.providers.mock.provider import MockRailwayProvider
from tests.api.conftest import JOURNEY_DATE, api_client


async def test_station_search_returns_codes_and_is_cached() -> None:
    provider = MockRailwayProvider()
    async with api_client(provider=provider) as (client, _):
        first = await client.get("/api/v1/stations/search", params={"q": "Tirur"})
        second = await client.get("/api/v1/stations/search", params={"q": "  tirur "})
    assert first.status_code == 200
    body = first.json()
    assert body["data_mode"] == "DEMO"
    assert body["items"][0]["code"] == "TIR"
    assert second.json() == body
    assert provider.calls["station_search"] == 1  # normalized query hits the cache


async def test_station_search_rejects_short_queries_without_provider_call() -> None:
    provider = MockRailwayProvider()
    async with api_client(provider=provider) as (client, _):
        response = await client.get("/api/v1/stations/search", params={"q": "ti"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_STATION_QUERY"
    assert provider.calls["station_search"] == 0


async def test_train_search(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/trains/search",
        json={"source": "tir", "destination": "TVC", "journey_date": JOURNEY_DATE.isoformat()},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "TIR"  # normalized
    assert [t["train_number"] for t in body["trains"]] == ["90601", "90603"]
    assert all(t["serves_requested_stations"] for t in body["trains"])
    assert (body["trains"][0]["boards_at_name"], body["trains"][0]["alights_at_name"]) == (
        "Tirur",
        "Thiruvananthapuram Central",
    )
    assert body["trains"][0]["departure_time"] is not None


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        (
            {"source": "TIR", "destination": "TIR", "journey_date": "2026-11-20"},
            422,
            "INVALID_JOURNEY",
        ),
        (
            {"source": "TIR", "destination": "TVC", "journey_date": "2026-11-01"},
            400,
            "INVALID_JOURNEY_DATE",
        ),
        (
            {"source": "TIR", "destination": "TVC", "journey_date": "2027-03-01"},
            400,
            "INVALID_JOURNEY_DATE",
        ),
        (
            {"source": "T!R", "destination": "TVC", "journey_date": "2026-11-20"},
            400,
            "INVALID_REQUEST",
        ),
        (
            {"source": "TIR", "destination": "TVC", "journey_date": "20-11-2026"},
            400,
            "INVALID_REQUEST",
        ),
        ({"source": "TIR", "destination": "TVC"}, 400, "INVALID_REQUEST"),
        (
            {"source": "TIR", "destination": "TVC", "journey_date": "2026-11-20", "x": 1},
            400,
            "INVALID_REQUEST",
        ),
    ],
)
async def test_train_search_validation(
    client: httpx.AsyncClient, payload: dict[str, object], status: int, code: str
) -> None:
    response = await client.post("/api/v1/trains/search", json=payload)
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert error["request_id"]


async def test_validation_errors_list_fields(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/trains/search", json={"source": "TIR"})
    fields = {f["field"] for f in response.json()["error"]["details"]["fields"]}
    assert {"destination", "journey_date"} <= fields


async def test_train_route_is_ordered_and_verified(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/trains/90601/route")
    assert response.status_code == 200
    body = response.json()
    assert body["route_verified"] is True
    assert [s["sequence"] for s in body["stops"]] == list(range(len(body["stops"])))
    assert body["stops"][0]["arrival"] is None
    assert body["stops"][-1]["departure"] is None
    assert body["classes"] == ["2A", "3A", "SL"]


async def test_unknown_train_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/trains/99999/route")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TRAIN_NOT_FOUND"


async def test_bad_train_number_is_400(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/trains/12a45/route")
    assert response.status_code == 400


class CodeLookupProvider(MockRailwayProvider):
    """Name search never matches codes (like RailKit); codes resolve via get_station."""

    def __init__(self, *, fail_lookup: bool = False) -> None:
        super().__init__()
        self.fail_lookup = fail_lookup

    async def search_stations(self, query: str) -> list[Station]:
        self.calls["station_search"] += 1
        if query.strip().lower().startswith("thiru"):
            return [Station("TVC", "Thiruvananthapuram Central")]
        return []

    async def get_station(self, code: str) -> Station | None:
        self.calls["station_lookup"] += 1
        if self.fail_lookup:
            raise ProviderTimeoutError("slow", provider="MOCK", endpoint="station_lookup")
        return Station("TVCN", "THIRUVANANTHAPURAM NORTH") if code == "TVCN" else None


async def test_station_codes_are_found_by_exact_lookup_and_cached() -> None:
    provider = CodeLookupProvider()
    async with api_client(provider=provider) as (client, _):
        first = (await client.get("/api/v1/stations/search", params={"q": "tvcn"})).json()
        again = (await client.get("/api/v1/stations/search", params={"q": "TVCN"})).json()
        missing = [
            (await client.get("/api/v1/stations/search", params={"q": "zzzz"})).json()
            for _ in range(2)
        ]
    assert first["items"][0]["code"] == "TVCN"
    assert again == first
    assert all(m["items"] == [] for m in missing)
    assert provider.calls["station_lookup"] == 2  # TVCN once, ZZZZ once ("not found" is cached too)


async def test_name_queries_do_not_spend_a_code_lookup() -> None:
    provider = CodeLookupProvider()
    async with api_client(provider=provider) as (client, _):
        body = (await client.get("/api/v1/stations/search", params={"q": "thiruvan"})).json()
    assert [s["code"] for s in body["items"]] == ["TVC"]
    assert provider.calls["station_lookup"] == 0


async def test_failed_code_lookup_still_returns_name_results() -> None:
    provider = CodeLookupProvider(fail_lookup=True)
    async with api_client(provider=provider) as (client, _):
        response = await client.get("/api/v1/stations/search", params={"q": "tvcn"})
    assert response.status_code == 200
    assert response.json()["items"] == []
