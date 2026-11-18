"""Composition root: turns Settings into wired services; the only place choosing implementations."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.api.rate_limit import ApiRateLimiter
from app.cache.singleflight import SingleFlight
from app.cache.store import KeyValueStore, MemoryStore, NamespacedStore, RedisStore
from app.cache.typed_cache import TypedCache
from app.core.clock import Clock, SystemClock
from app.core.config import Environment, ExecutionMode, ProviderName, Settings
from app.database.session import create_engine
from app.providers.base import RailwayProvider
from app.providers.factory import build_provider
from app.repositories.base import Persistence, PersistenceError
from app.repositories.memory import InMemoryPersistence
from app.repositories.sqlalchemy import SqlAlchemyPersistence
from app.services.availability import AvailabilityService
from app.services.executor import InlineExecutor, InProcessExecutor, SearchExecutor
from app.services.journey_search import JourneySearchService
from app.services.quota import ProviderQuotaGuard
from app.services.quota_eligibility import QuotaEligibilityService
from app.services.stations import StationService
from app.services.trains import TrainService
from app.services.usage import CompositeObserver, ProviderUsageRecorder

logger = logging.getLogger(__name__)

ReadinessCheck = Callable[[], Awaitable[None]]
Closer = Callable[[], Awaitable[None]]


@dataclass
class AppContainer:
    settings: Settings
    clock: Clock
    store: KeyValueStore
    persistence: Persistence
    provider: RailwayProvider
    quota_guard: ProviderQuotaGuard
    usage: ProviderUsageRecorder
    stations: StationService
    trains: TrainService
    availability: AvailabilityService
    eligibility: QuotaEligibilityService
    journeys: JourneySearchService
    executor: SearchExecutor
    rate_limiter: ApiRateLimiter
    readiness_checks: dict[str, ReadinessCheck] = field(default_factory=dict)
    _closers: list[Closer] = field(default_factory=list)

    @property
    def data_mode(self) -> str:
        return "LIVE" if self.provider.is_live else "DEMO"

    @classmethod
    async def build(
        cls,
        settings: Settings,
        *,
        clock: Clock | None = None,
        provider: RailwayProvider | None = None,
        store: KeyValueStore | None = None,
        persistence: Persistence | None = None,
    ) -> AppContainer:
        clock = clock or SystemClock()
        closers: list[Closer] = []
        checks: dict[str, ReadinessCheck] = {}

        if store is None:
            if settings.redis_url is not None:
                redis = RedisStore.from_url(settings.redis_url.get_secret_value())
                store = redis
                checks["redis"] = redis.ping
            else:
                if settings.railway_provider is ProviderName.RAILKIT:
                    logger.warning(
                        "REDIS_URL not set: provider quota guard and cache are per-process; "
                        "run exactly one worker"
                    )
                store = MemoryStore()
            closers.append(store.aclose)
        namespaced = NamespacedStore(store, f"railroute:{settings.environment.value}:")

        if persistence is None:
            if settings.database_url is not None:
                engine = create_engine(
                    settings.database_url.get_secret_value(),
                    pool_size=settings.database_pool_size,
                    max_overflow=settings.database_max_overflow,
                    echo=settings.database_echo,
                )
                persistence = SqlAlchemyPersistence(engine)
                checks["database"] = persistence.ping
            else:
                if settings.environment not in (Environment.DEVELOPMENT, Environment.TEST):
                    raise RuntimeError("DATABASE_URL is required outside development/test")
                logger.warning("DATABASE_URL not set: searches are kept in memory only")
                persistence = InMemoryPersistence()
            closers.append(persistence.aclose)

        guard = ProviderQuotaGuard(
            namespaced,
            clock=clock,
            window_limit=settings.provider_window_request_limit,
            window_seconds=settings.provider_window_seconds,
            monthly_limit=settings.provider_monthly_request_limit,
            backoff_seconds=settings.provider_rate_limit_backoff_seconds,
        )
        usage = ProviderUsageRecorder(persistence, clock=clock)
        if provider is None:
            provider = build_provider(
                settings, clock=clock, observer=CompositeObserver([guard, usage])
            )
        closers.append(provider.aclose)

        cache = TypedCache(namespaced)
        flight = SingleFlight(namespaced, lock_ttl_seconds=settings.single_flight_lock_ttl_seconds)
        stations = StationService(
            provider=provider,
            cache=cache,
            flight=flight,
            persistence=persistence,
            ttl_seconds=settings.station_search_cache_ttl_seconds,
            min_query_length=settings.station_search_min_query_length,
        )
        trains = TrainService(
            provider=provider,
            cache=cache,
            flight=flight,
            persistence=persistence,
            clock=clock,
            search_ttl_seconds=settings.train_search_cache_ttl_seconds,
            route_ttl_seconds=settings.train_route_cache_ttl_seconds,
        )
        availability = AvailabilityService(
            provider=provider,
            cache=cache,
            flight=flight,
            persistence=persistence,
            clock=clock,
            ttl_seconds=settings.availability_cache_ttl_seconds,
        )
        executor: SearchExecutor = (
            InlineExecutor()
            if settings.search_execution_mode is ExecutionMode.SYNC
            else InProcessExecutor(
                max_concurrent=settings.max_concurrent_searches,
                shutdown_grace_seconds=settings.search_shutdown_grace_seconds,
            )
        )
        eligibility = QuotaEligibilityService(
            settings=settings, clock=clock, supported_quotas=provider.supported_quotas
        )
        journeys = JourneySearchService(
            settings=settings,
            clock=clock,
            trains=trains,
            availability=availability,
            eligibility=eligibility,
            persistence=persistence,
            executor=executor,
            provider_name=provider.name,
            data_mode="LIVE" if provider.is_live else "DEMO",
            store=namespaced,
        )
        rate_limiter = ApiRateLimiter(
            namespaced,
            window_seconds=settings.api_rate_limit_window_seconds,
            limits={
                "search": settings.api_rate_limit_search_requests,
                "lookup": settings.api_rate_limit_lookup_requests,
            },
            trusted_hops=settings.trusted_proxy_hops,
        )

        if persistence.durable:
            try:
                failed = await persistence.fail_unfinished_searches(
                    error_code="INTERRUPTED", now=clock.now(), stale_before=journeys.stale_before()
                )
                if failed:
                    logger.warning("marked interrupted searches failed", extra={"count": failed})
            except PersistenceError:
                logger.error("database unavailable at startup; readiness will report failure")

        if provider.is_live and not settings.availability_date_policy_verified:
            logger.warning(
                "AVAILABILITY_DATE_POLICY contradicts observed RailKit behaviour "
                "(boarding date at the segment's from-station); after-midnight segments may be "
                "checked for the wrong train run",
                extra={"policy": settings.availability_date_policy.value},
            )

        usage.start()
        closers.append(usage.aclose)
        closers.append(executor.aclose)

        container = cls(
            settings=settings,
            clock=clock,
            store=namespaced,
            persistence=persistence,
            provider=provider,
            quota_guard=guard,
            usage=usage,
            stations=stations,
            trains=trains,
            availability=availability,
            eligibility=eligibility,
            journeys=journeys,
            executor=executor,
            rate_limiter=rate_limiter,
            readiness_checks=checks,
            _closers=closers,
        )
        logger.info(
            "container ready",
            extra={
                "environment": settings.environment.value,
                "provider": provider.name,
                "data_mode": container.data_mode,
                "durable": persistence.durable,
                "distributed_store": namespaced.distributed,
                "execution_mode": settings.search_execution_mode.value,
            },
        )
        return container

    def on_close(self, closer: Closer) -> None:
        self._closers.append(closer)

    async def aclose(self) -> None:
        for closer in reversed(self._closers):
            try:
                await closer()
            except Exception:
                logger.exception("error while closing resource")
        self._closers.clear()
