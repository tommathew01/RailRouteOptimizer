"""Segment availability checks: cache → single-flight → search budget → provider (FR-008, FR-016).

Only interpretable observations (status other than UNKNOWN) are cached. Every observation is
persisted (append-only) *before* it is cached, so cached entries always reference durable rows.
Provider failures are returned as outcomes, never converted into NOT_AVAILABLE.

Budget accounting (D-28): cache hits and results shared through single-flight are free. A call
that goes to the provider reserves one attempt, every retry must reserve another, and the call is
settled against the attempts actually made — so the search budget counts real provider requests.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date

from pydantic import TypeAdapter

from app.cache import keys
from app.cache.singleflight import SingleFlight
from app.cache.typed_cache import TypedCache
from app.core import metrics
from app.core.clock import Clock
from app.domain.enums import AvailabilityStatus, SegmentQueryOutcome
from app.domain.models import AvailabilityQuery, SegmentKey, SegmentObservation
from app.providers.base import RailwayProvider, call_gate
from app.providers.errors import ProviderError, ProviderErrorCategory
from app.repositories.base import Persistence
from app.repositories.records import SegmentRunRecord
from app.services.quota import SearchBudget

logger = logging.getLogger(__name__)
_OBSERVATION = TypeAdapter(SegmentObservation)


@dataclass(frozen=True, slots=True)
class SegmentRequest:
    key: SegmentKey
    provider_date: date


@dataclass(frozen=True, slots=True)
class SegmentCheckResult:
    request: SegmentRequest
    #: ``None`` when the per-search budget refused the call before it was attempted.
    outcome: SegmentQueryOutcome | None
    observation: SegmentObservation | None = None
    cache_hit: bool = False
    error: ProviderError | None = None
    latency_ms: float | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome is SegmentQueryOutcome.SUCCESS and self.observation is not None


class _BudgetRefusedError(Exception):
    pass


def run_record(
    result: SegmentCheckResult, *, search_id: uuid.UUID | None, clock: Clock
) -> SegmentRunRecord | None:
    if result.outcome is None:
        return None
    return SegmentRunRecord(
        id=uuid.uuid4(),
        search_id=search_id,
        key=result.request.key,
        provider_date=result.request.provider_date,
        outcome=result.outcome,
        cache_hit=result.cache_hit,
        created_at=clock.now(),
        latency_ms=result.latency_ms,
        error_code=result.outcome.value if result.error else None,
        error_message=result.error.message if result.error else None,
        observation_id=result.observation.id if result.observation else None,
    )


class AvailabilityService:
    def __init__(
        self,
        *,
        provider: RailwayProvider,
        cache: TypedCache,
        flight: SingleFlight,
        persistence: Persistence,
        clock: Clock,
        ttl_seconds: int,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._flight = flight
        self._persistence = persistence
        self._clock = clock
        self._ttl = ttl_seconds

    async def check(
        self, request: SegmentRequest, *, budget: SearchBudget | None = None
    ) -> SegmentCheckResult:
        cache_key = keys.availability(self._provider.name, request.key, request.provider_date)
        cached = await self._cache.get(cache_key, _OBSERVATION)
        if cached is not None:
            metrics.CACHE_LOOKUPS.labels("availability", "hit").inc()
            return SegmentCheckResult(request, SegmentQueryOutcome.SUCCESS, cached, cache_hit=True)

        started = time.perf_counter()

        async def compute() -> SegmentObservation:
            call = None
            if budget is not None:
                call = await budget.start_call()
                if call is None:
                    raise _BudgetRefusedError
            key = request.key
            query = AvailabilityQuery(
                train_number=key.train_number,
                from_station=key.from_station,
                to_station=key.to_station,
                journey_date=request.provider_date,
                travel_class=key.travel_class,
                quota=key.quota,
            )
            # A guard refusal before the first attempt never reached the provider; anything else
            # (success, provider error, cancellation mid-request) did.
            reached = True
            try:
                with call_gate(call):
                    record = await self._provider.get_availability(query)
            except ProviderError as error:
                reached = error.category is not ProviderErrorCategory.QUOTA_EXHAUSTED
                raise
            finally:
                if call is not None:
                    await call.settle(reached_provider=reached)
            observation = SegmentObservation(
                id=uuid.uuid4(),
                key=key,
                provider_date=request.provider_date,
                record=record,
                observed_at=self._clock.now(),
            )
            await self._persistence.add_observations([observation])
            if record.status is not AvailabilityStatus.UNKNOWN:
                await self._cache.set(cache_key, observation, _OBSERVATION, self._ttl)
            return observation

        try:
            observation, shared = await self._flight.run(
                cache_key,
                compute=compute,
                load_cached=lambda: self._cache.get(cache_key, _OBSERVATION),
            )
        except _BudgetRefusedError:
            return SegmentCheckResult(request, None)
        except ProviderError as error:
            if error.category is ProviderErrorCategory.INVALID_RESPONSE:
                metrics.MALFORMED_RESPONSES.labels(error.provider, error.endpoint).inc()
                logger.warning(
                    "invalid provider response",
                    extra={"endpoint": error.endpoint, "diagnostics": error.diagnostics},
                )
            if error.category is ProviderErrorCategory.QUOTA_EXHAUSTED:
                metrics.QUOTA_REFUSALS.labels(
                    error.provider, str(error.diagnostics.get("reason", "UNKNOWN"))
                ).inc()
            return SegmentCheckResult(
                request,
                error.outcome,
                error=error,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        metrics.CACHE_LOOKUPS.labels("availability", "shared" if shared else "miss").inc()
        return SegmentCheckResult(
            request,
            SegmentQueryOutcome.SUCCESS,
            observation,
            cache_hit=shared,
            latency_ms=None if shared else round((time.perf_counter() - started) * 1000, 1),
        )
