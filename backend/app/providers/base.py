"""Internal provider interface (doc 07 §5). The optimizer never sees provider DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from app.domain.enums import Quota
from app.domain.models import (
    AvailabilityQuery,
    AvailabilityRecord,
    Station,
    TrainRoute,
    TrainSummary,
)


@runtime_checkable
class RailwayProvider(Protocol):
    @property
    def name(self) -> str:
        """Stable provider identifier stored with every observation (e.g. ``RAILKIT``)."""
        ...

    @property
    def is_live(self) -> bool:
        """``False`` for simulated (demo) data; drives the DEMO labelling everywhere."""
        ...

    @property
    def supported_quotas(self) -> frozenset[Quota]:
        """Quotas the availability endpoint accepts. Others are never sent (no substitution)."""
        ...

    async def search_stations(self, query: str) -> list[Station]: ...

    async def get_station(self, code: str) -> Station | None:
        """Exact lookup by station code; ``None`` when the provider has no such station."""
        ...

    async def search_trains(
        self, source: str, destination: str, journey_date: date
    ) -> list[TrainSummary]: ...

    async def get_train_route(self, train_number: str) -> TrainRoute: ...

    async def get_availability(self, query: AvailabilityQuery) -> AvailabilityRecord: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ProviderRequestEvent:
    """One HTTP attempt against a provider (retries produce one event each)."""

    provider: str
    endpoint: str
    attempt: int
    outcome: str
    status_code: int | None
    latency_ms: float
    retry_after_seconds: float | None = None


class ProviderRequestObserver(Protocol):
    """Hook around every provider HTTP attempt: quota guard, usage accounting, metrics."""

    async def before_request(self, provider: str, endpoint: str) -> None:
        """May raise :class:`~app.providers.errors.ProviderQuotaExhaustedError`."""
        ...

    async def after_request(self, event: ProviderRequestEvent) -> None: ...


class NullRequestObserver:
    async def before_request(self, provider: str, endpoint: str) -> None:
        return None

    async def after_request(self, event: ProviderRequestEvent) -> None:
        return None
