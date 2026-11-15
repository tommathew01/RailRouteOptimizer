"""Train discovery and route retrieval (FR-004, FR-005) with caching and route persistence."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from pydantic import TypeAdapter

from app.cache import keys
from app.cache.singleflight import SingleFlight
from app.cache.typed_cache import TypedCache
from app.core import metrics
from app.core.clock import Clock
from app.domain.models import TrainRoute, TrainSummary
from app.domain.route import RouteAnalysis, analyze_route
from app.providers.base import RailwayProvider
from app.repositories.base import Persistence, PersistenceError

logger = logging.getLogger(__name__)
_TRAINS = TypeAdapter(list[TrainSummary])
_ROUTE = TypeAdapter(TrainRoute)


class TrainService:
    def __init__(
        self,
        *,
        provider: RailwayProvider,
        cache: TypedCache,
        flight: SingleFlight,
        persistence: Persistence,
        clock: Clock,
        search_ttl_seconds: int,
        route_ttl_seconds: int,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._flight = flight
        self._persistence = persistence
        self._clock = clock
        self._search_ttl = search_ttl_seconds
        self._route_ttl = route_ttl_seconds

    async def search_trains(
        self, source: str, destination: str, journey_date: date
    ) -> list[TrainSummary]:
        cache_key = keys.train_search(self._provider.name, source, destination, journey_date)
        cached = await self._cache.get(cache_key, _TRAINS)
        if cached is not None:
            metrics.CACHE_LOOKUPS.labels("train_search", "hit").inc()
            return cached

        async def compute() -> list[TrainSummary]:
            trains = await self._provider.search_trains(source, destination, journey_date)
            await self._cache.set(cache_key, trains, _TRAINS, self._search_ttl)
            return trains

        trains, shared = await self._flight.run(
            cache_key, compute=compute, load_cached=lambda: self._cache.get(cache_key, _TRAINS)
        )
        metrics.CACHE_LOOKUPS.labels("train_search", "shared" if shared else "miss").inc()
        return trains

    async def get_route(self, train_number: str) -> tuple[TrainRoute, RouteAnalysis]:
        route = await self._load_route(train_number)
        return route, analyze_route(route)

    async def _load_route(self, train_number: str) -> TrainRoute:
        cache_key = keys.train_route(self._provider.name, train_number)
        cached = await self._cache.get(cache_key, _ROUTE)
        if cached is not None:
            metrics.CACHE_LOOKUPS.labels("train_route", "hit").inc()
            return cached
        if self._route_ttl > 0:
            try:
                stored = await self._persistence.get_recent_route(
                    train_number,
                    fetched_after=self._clock.now() - timedelta(seconds=self._route_ttl),
                )
            except PersistenceError:
                stored = None
            if stored is not None and stored.provider == self._provider.name:
                metrics.CACHE_LOOKUPS.labels("train_route", "database").inc()
                await self._cache.set(cache_key, stored, _ROUTE, self._route_ttl)
                return stored

        async def compute() -> TrainRoute:
            route = await self._provider.get_train_route(train_number)
            analysis = analyze_route(route)
            try:
                await self._persistence.save_route(
                    route, verified=analysis.verified, issues=[i.value for i in analysis.issues]
                )
            except PersistenceError:
                logger.warning("could not persist train route", extra={"train": train_number})
            await self._cache.set(cache_key, route, _ROUTE, self._route_ttl)
            return route

        route, shared = await self._flight.run(
            cache_key, compute=compute, load_cached=lambda: self._cache.get(cache_key, _ROUTE)
        )
        metrics.CACHE_LOOKUPS.labels("train_route", "shared" if shared else "miss").inc()
        return route
