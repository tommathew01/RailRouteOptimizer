"""In-memory persistence gateway for tests and zero-infrastructure demo mode (not durable)."""

from __future__ import annotations

import copy
import uuid
from collections.abc import Sequence
from datetime import datetime

from app.domain.enums import SearchStatus
from app.domain.models import SegmentObservation, Station, TrainRoute
from app.repositories.records import (
    ProviderUsageRecord,
    RecommendationRecord,
    SearchRecord,
    SegmentRunRecord,
)


class InMemoryPersistence:
    def __init__(self) -> None:
        self.searches: dict[uuid.UUID, SearchRecord] = {}
        self.observations: dict[uuid.UUID, SegmentObservation] = {}
        self.segment_runs: list[SegmentRunRecord] = []
        self.recommendations: list[RecommendationRecord] = []
        self.provider_usage: list[ProviderUsageRecord] = []
        self.stations: dict[str, Station] = {}
        self.routes: dict[str, tuple[TrainRoute, bool, tuple[str, ...]]] = {}

    @property
    def durable(self) -> bool:
        return False

    async def create_search(self, search: SearchRecord) -> None:
        if search.id in self.searches:
            raise ValueError("duplicate search id")
        self.searches[search.id] = copy.deepcopy(search)

    async def save_search(self, search: SearchRecord) -> None:
        self.searches[search.id] = copy.deepcopy(search)

    async def get_search(self, search_id: uuid.UUID) -> SearchRecord | None:
        found = self.searches.get(search_id)
        return copy.deepcopy(found) if found else None

    async def fail_unfinished_searches(
        self, *, error_code: str, now: datetime, stale_before: datetime
    ) -> int:
        count = 0
        for search in self.searches.values():
            last_update = search.updated_at or search.created_at
            if (
                search.status in (SearchStatus.QUEUED, SearchStatus.RUNNING)
                and last_update < stale_before
            ):
                search.status = SearchStatus.FAILED
                search.error_code = error_code
                search.completed_at = search.updated_at = now
                count += 1
        return count

    async def add_observations(self, observations: Sequence[SegmentObservation]) -> None:
        for observation in observations:
            self.observations.setdefault(observation.id, observation)

    async def add_segment_runs(self, runs: Sequence[SegmentRunRecord]) -> None:
        self.segment_runs.extend(runs)

    async def save_recommendations(self, recommendations: Sequence[RecommendationRecord]) -> None:
        self.recommendations.extend(recommendations)

    async def add_provider_usage(self, events: Sequence[ProviderUsageRecord]) -> None:
        self.provider_usage.extend(events)

    async def upsert_stations(self, stations: Sequence[Station], *, authoritative: bool) -> None:
        for station in stations:
            if authoritative or station.code not in self.stations:
                self.stations[station.code] = station

    async def save_route(self, route: TrainRoute, *, verified: bool, issues: Sequence[str]) -> None:
        self.routes[route.train_number] = (route, verified, tuple(issues))

    async def get_recent_route(
        self, train_number: str, *, fetched_after: datetime
    ) -> TrainRoute | None:
        found = self.routes.get(train_number)
        if found is None or found[0].fetched_at <= fetched_after:
            return None
        return found[0]

    async def ping(self) -> None:
        return None

    async def aclose(self) -> None:
        return None
