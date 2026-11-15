"""RailKit implementation of :class:`app.providers.base.RailwayProvider`."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from app.core.clock import Clock
from app.domain.enums import Quota
from app.domain.models import (
    AvailabilityQuery,
    AvailabilityRecord,
    Station,
    TrainRoute,
    TrainSummary,
)
from app.integrations.railkit.client import PROVIDER_NAME, RailKitHttpClient, path_segment
from app.integrations.railkit.dates import to_railkit_date
from app.integrations.railkit.mapper import (
    map_availability,
    map_station,
    map_stations,
    map_train_route,
    map_train_search,
)
from app.providers.errors import ProviderNotFoundError, ProviderRejectedError


class RailKitProvider:
    def __init__(
        self,
        client: RailKitHttpClient,
        *,
        clock: Clock,
        fare_currency: str,
        secret_fragments: Sequence[str] = (),
        supported_quotas: Iterable[Quota] = (Quota.GENERAL, Quota.TATKAL),
    ) -> None:
        self._client = client
        # Live 2026-11-15 (docs/09 Q16): TQ accepted by seat availability.
        self._quotas = frozenset(supported_quotas)
        self._clock = clock
        self._fare_currency = fare_currency
        self._secret_fragments = tuple(secret_fragments)

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def is_live(self) -> bool:
        return True

    @property
    def supported_quotas(self) -> frozenset[Quota]:
        return self._quotas

    @property
    def http(self) -> RailKitHttpClient:
        return self._client

    async def search_stations(self, query: str) -> list[Station]:
        data = await self._client.get_data(
            "station_search", "/api/v1/stations/search", params={"name": query}
        )
        return map_stations(data)

    async def get_station(self, code: str) -> Station | None:
        try:
            data = await self._client.get_data(
                "station_lookup", f"/api/v1/stations/{path_segment(code.upper())}"
            )
        except (ProviderNotFoundError, ProviderRejectedError):
            return None
        return map_station(data)

    async def search_trains(
        self, source: str, destination: str, journey_date: date
    ) -> list[TrainSummary]:
        path = f"/api/v1/trains/between/{path_segment(source)}/{path_segment(destination)}"
        data = await self._client.get_data(
            "train_search", path, params={"date": to_railkit_date(journey_date)}
        )
        return map_train_search(data)

    async def get_train_route(self, train_number: str) -> TrainRoute:
        data = await self._client.get_data(
            "train_info", f"/api/v1/trains/{path_segment(train_number)}/info"
        )
        return map_train_route(data, train_number=train_number, fetched_at=self._clock.now())

    async def get_availability(self, query: AvailabilityQuery) -> AvailabilityRecord:
        if query.quota not in self._quotas:  # never spend a request on a known rejection
            raise ProviderRejectedError(
                f"quota {query.quota.value} is not supported by this provider",
                provider=PROVIDER_NAME,
                endpoint="seat_availability",
            )
        parts = (
            query.train_number,
            query.from_station,
            query.to_station,
            to_railkit_date(query.journey_date),
            query.travel_class,
            query.quota.value,
        )
        path = "/api/v1/seats/" + "/".join(path_segment(p) for p in parts)
        data = await self._client.get_data("seat_availability", path)
        return map_availability(
            data,
            query,
            fare_currency=self._fare_currency,
            secret_fragments=self._secret_fragments,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
