"""Station search (FR-001): cached, single-flight, never called for very short queries."""

from __future__ import annotations

import logging
import re

from pydantic import TypeAdapter

from app.cache import keys
from app.cache.singleflight import SingleFlight
from app.cache.typed_cache import TypedCache
from app.core import metrics
from app.core.errors import InvalidRequestError
from app.domain.models import Station
from app.providers.base import RailwayProvider
from app.providers.errors import ProviderError
from app.repositories.base import Persistence, PersistenceError

logger = logging.getLogger(__name__)
_STATIONS = TypeAdapter(list[Station])
MAX_QUERY_LENGTH = 50
#: Typed text that could be a station code (e.g. "TVCN"). Name search does not match codes, so
#: such queries also get an exact code lookup (cached, including "not found").
_CODE_LIKE = re.compile(r"^[a-z0-9]{3,5}$")


class StationService:
    def __init__(
        self,
        *,
        provider: RailwayProvider,
        cache: TypedCache,
        flight: SingleFlight,
        persistence: Persistence,
        ttl_seconds: int,
        min_query_length: int,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._flight = flight
        self._persistence = persistence
        self._ttl = ttl_seconds
        self._min_length = min_query_length

    async def search(self, query: str) -> list[Station]:
        normalized = keys.normalize_station_query(query)
        if len(normalized) < self._min_length or len(normalized) > MAX_QUERY_LENGTH:
            raise InvalidRequestError(
                f"Type between {self._min_length} and {MAX_QUERY_LENGTH} characters.",
                code="INVALID_STATION_QUERY",
            )
        stations = await self._search_by_name(normalized)
        code = normalized.upper()
        if _CODE_LIKE.match(normalized) and all(s.code != code for s in stations):
            exact = await self._lookup_code(code)
            if exact is not None:
                stations = [exact, *stations][:10]
        return stations

    async def _lookup_code(self, code: str) -> Station | None:
        cache_key = keys.station_code(self._provider.name, code)
        cached = await self._cache.get(cache_key, _STATIONS)
        if cached is not None:
            metrics.CACHE_LOOKUPS.labels("station_code", "hit").inc()
            return cached[0] if cached else None

        async def compute() -> list[Station]:
            found = await self._provider.get_station(code)
            result = [found] if found is not None else []
            if result:
                try:
                    await self._persistence.upsert_stations(result, authoritative=True)
                except PersistenceError:
                    logger.warning("could not record station in catalog")
            await self._cache.set(cache_key, result, _STATIONS, self._ttl)
            return result

        try:
            result, shared = await self._flight.run(
                cache_key,
                compute=compute,
                load_cached=lambda: self._cache.get(cache_key, _STATIONS),
            )
        except ProviderError as error:
            # The name results are still useful; never fail the search over the code lookup.
            logger.warning("station code lookup failed", extra={"category": error.category.value})
            return None
        metrics.CACHE_LOOKUPS.labels("station_code", "shared" if shared else "miss").inc()
        return result[0] if result else None

    async def _search_by_name(self, normalized: str) -> list[Station]:
        cache_key = keys.station_search(self._provider.name, normalized)
        cached = await self._cache.get(cache_key, _STATIONS)
        if cached is not None:
            metrics.CACHE_LOOKUPS.labels("station_search", "hit").inc()
            return cached

        async def compute() -> list[Station]:
            stations = await self._provider.search_stations(normalized)
            try:
                await self._persistence.upsert_stations(stations, authoritative=True)
            except PersistenceError:
                logger.warning("could not record stations in catalog")
            await self._cache.set(cache_key, stations, _STATIONS, self._ttl)
            return stations

        stations, shared = await self._flight.run(
            cache_key, compute=compute, load_cached=lambda: self._cache.get(cache_key, _STATIONS)
        )
        metrics.CACHE_LOOKUPS.labels("station_search", "shared" if shared else "miss").inc()
        return stations
