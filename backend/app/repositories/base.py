"""Persistence gateway used by the services layer (PostgreSQL in production)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.domain.models import SegmentObservation, Station, TrainRoute
from app.repositories.records import (
    ProviderUsageRecord,
    RecommendationRecord,
    SearchRecord,
    SegmentRunRecord,
)


class PersistenceError(Exception):
    """The database is unavailable or rejected a write. Results must not be reported as saved."""


class Persistence(Protocol):
    @property
    def durable(self) -> bool:
        """False for the in-memory gateway (demo/tests): nothing survives a restart."""
        ...

    async def create_search(self, search: SearchRecord) -> None: ...

    async def save_search(self, search: SearchRecord) -> None:
        """Persist mutable search state (status, counters, completeness, result snapshot)."""
        ...

    async def get_search(self, search_id: uuid.UUID) -> SearchRecord | None: ...

    async def fail_unfinished_searches(
        self, *, error_code: str, now: datetime, stale_before: datetime
    ) -> int:
        """Mark QUEUED/RUNNING searches not updated since ``stale_before`` as FAILED.

        Only *stale* searches are reaped, so a replica starting up never fails searches that
        other healthy replicas are still running. The result snapshot is kept as-is.
        """
        ...

    async def add_observations(self, observations: Sequence[SegmentObservation]) -> None: ...

    async def add_segment_runs(self, runs: Sequence[SegmentRunRecord]) -> None: ...

    async def save_recommendations(
        self, recommendations: Sequence[RecommendationRecord]
    ) -> None: ...

    async def add_provider_usage(self, events: Sequence[ProviderUsageRecord]) -> None: ...

    async def upsert_stations(self, stations: Sequence[Station], *, authoritative: bool) -> None:
        """``authoritative`` (station search) may update names; route data only fills gaps."""
        ...

    async def save_route(
        self, route: TrainRoute, *, verified: bool, issues: Sequence[str]
    ) -> None: ...

    async def get_recent_route(
        self, train_number: str, *, fetched_after: datetime
    ) -> TrainRoute | None: ...

    async def ping(self) -> None: ...

    async def aclose(self) -> None: ...
