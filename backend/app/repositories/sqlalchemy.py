"""PostgreSQL implementation of the persistence gateway (SQLAlchemy 2.x async)."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.database import session as db_session
from app.database.models import (
    AvailabilityObservationRow,
    JourneySearchRow,
    ProviderUsageRow,
    RecommendationRow,
    RecommendationSegmentRow,
    SegmentQueryRunRow,
    StationRow,
    TrainRouteRow,
    TrainRow,
    TrainStopRow,
)
from app.domain.enums import IncompleteReason, SearchCompleteness, SearchStatus
from app.domain.models import (
    SegmentObservation,
    Station,
    TrainRoute,
    TrainStop,
    is_valid_station_code,
)
from app.repositories.base import PersistenceError
from app.repositories.records import (
    ProviderUsageRecord,
    RecommendationRecord,
    SearchRecord,
    SegmentRunRecord,
)


def route_version(route: TrainRoute) -> str:
    """Stable fingerprint of the stop sequence (provider route changes create a new version)."""
    material = [
        (s.station_code, str(s.arrival_time), str(s.departure_time), s.day_offset)
        for s in route.stops
    ]
    return hashlib.sha256(json.dumps(material).encode()).hexdigest()


def _search_from_row(row: JourneySearchRow) -> SearchRecord:
    return SearchRecord(
        id=row.id,
        source=row.source_station_code,
        destination=row.destination_station_code,
        journey_date=row.journey_date,
        classes=list(row.classes),
        filters=dict(row.filters),
        train_numbers=list(row.train_numbers) if row.train_numbers is not None else None,
        max_segments=row.max_segments,
        request_budget=row.request_budget,
        provider=row.provider,
        created_at=row.created_at,
        quotas=list(row.quotas) if row.quotas else [row.quota],
        status=SearchStatus(row.status),
        search_completeness=(
            SearchCompleteness(row.search_completeness) if row.search_completeness else None
        ),
        incomplete_reason=IncompleteReason(row.incomplete_reason)
        if row.incomplete_reason
        else None,
        requests_made=row.requests_made,
        cache_hits=row.cache_hits,
        error_code=row.error_code,
        result_snapshot=row.result_snapshot,
        started_at=row.started_at,
        completed_at=row.completed_at,
        updated_at=row.updated_at,
    )


def _observation_row(obs: SegmentObservation) -> dict[str, Any]:
    record = obs.record
    prediction = record.prediction
    return {
        "id": obs.id,
        "train_number": obs.key.train_number,
        "train_start_date": obs.key.train_start_date,
        "journey_date": obs.provider_date,
        "source_station_code": obs.key.from_station,
        "destination_station_code": obs.key.to_station,
        "travel_class": obs.key.travel_class,
        "quota": obs.key.quota.value,
        "status": record.status.value,
        "availability_text": record.availability_text,
        "raw_status": record.raw_status,
        "provider_status": record.provider_status,
        "waitlist_type": record.waitlist_type,
        "waitlist_number": record.waitlist_number,
        "rac_number": record.rac_number,
        "available_count": record.available_count,
        "can_book": record.can_book,
        "prediction_text": prediction.text if prediction else None,
        "prediction_percentage": (
            Decimal(str(prediction.percentage))
            if prediction and prediction.percentage is not None
            else None
        ),
        "prediction_percentage_source": (
            prediction.percentage_source.value
            if prediction and prediction.percentage_source
            else None
        ),
        "fare_amount": record.fare.amount if record.fare else None,
        "currency": record.fare.currency if record.fare else None,
        "fare_basis": record.fare.basis if record.fare else None,
        "provider": record.provider,
        "provider_checked_at": record.provider_checked_at,
        "observed_at": obs.observed_at,
        "anomalies": list(record.anomalies),
        "raw_payload": dict(record.raw_payload) if record.raw_payload is not None else None,
    }


class SqlAlchemyPersistence:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessions: async_sessionmaker[AsyncSession] = db_session.create_sessionmaker(engine)

    @property
    def durable(self) -> bool:
        return True

    @asynccontextmanager
    async def _tx(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self._sessions.begin() as session:
                yield session
        except SQLAlchemyError as exc:
            raise PersistenceError(type(exc).__name__) from exc

    # --- Searches -------------------------------------------------------------------------------
    async def create_search(self, search: SearchRecord) -> None:
        async with self._tx() as session:
            session.add(
                JourneySearchRow(
                    id=search.id,
                    source_station_code=search.source,
                    destination_station_code=search.destination,
                    journey_date=search.journey_date,
                    classes=search.classes,
                    quota=search.quota,
                    quotas=search.quotas,
                    filters=search.filters,
                    train_numbers=search.train_numbers,
                    max_segments=search.max_segments,
                    status=search.status.value,
                    request_budget=search.request_budget,
                    provider=search.provider,
                    created_at=search.created_at,
                    updated_at=search.created_at,
                )
            )

    async def save_search(self, search: SearchRecord) -> None:
        async with self._tx() as session:
            await session.execute(
                update(JourneySearchRow)
                .where(JourneySearchRow.id == search.id)
                .values(
                    status=search.status.value,
                    search_completeness=(
                        search.search_completeness.value if search.search_completeness else None
                    ),
                    incomplete_reason=(
                        search.incomplete_reason.value if search.incomplete_reason else None
                    ),
                    requests_made=search.requests_made,
                    cache_hits=search.cache_hits,
                    error_code=search.error_code,
                    result_snapshot=search.result_snapshot,
                    started_at=search.started_at,
                    completed_at=search.completed_at,
                    updated_at=search.updated_at or search.created_at,
                )
            )

    async def get_search(self, search_id: uuid.UUID) -> SearchRecord | None:
        async with self._tx() as session:
            row = await session.get(JourneySearchRow, search_id)
            return _search_from_row(row) if row else None

    async def fail_unfinished_searches(
        self, *, error_code: str, now: datetime, stale_before: datetime
    ) -> int:
        async with self._tx() as session:
            result = await session.execute(
                update(JourneySearchRow)
                .where(JourneySearchRow.status.in_([SearchStatus.QUEUED, SearchStatus.RUNNING]))
                .where(JourneySearchRow.updated_at < stale_before)
                .values(
                    status=SearchStatus.FAILED.value,
                    error_code=error_code,
                    completed_at=now,
                    updated_at=now,
                )
            )
            return int(getattr(result, "rowcount", 0) or 0)

    # --- Observations, runs, recommendations, usage -------------------------------------------
    async def add_observations(self, observations: Sequence[SegmentObservation]) -> None:
        if not observations:
            return
        async with self._tx() as session:
            await session.execute(
                insert(AvailabilityObservationRow)
                .values([_observation_row(o) for o in observations])
                .on_conflict_do_nothing(index_elements=["id"])
            )

    async def add_segment_runs(self, runs: Sequence[SegmentRunRecord]) -> None:
        if not runs:
            return
        async with self._tx() as session:
            session.add_all(
                SegmentQueryRunRow(
                    id=run.id,
                    search_id=run.search_id,
                    train_number=run.key.train_number,
                    train_start_date=run.key.train_start_date,
                    journey_date=run.provider_date,
                    source_station_code=run.key.from_station,
                    destination_station_code=run.key.to_station,
                    travel_class=run.key.travel_class,
                    quota=run.key.quota.value,
                    outcome=run.outcome.value,
                    provider_latency_ms=run.latency_ms,
                    cache_hit=run.cache_hit,
                    error_code=run.error_code,
                    error_message=run.error_message,
                    observation_id=run.observation_id,
                    created_at=run.created_at,
                )
                for run in runs
            )

    async def save_recommendations(self, recommendations: Sequence[RecommendationRecord]) -> None:
        if not recommendations:
            return
        async with self._tx() as session:
            for rec in recommendations:
                row = RecommendationRow(
                    id=rec.id,
                    search_id=rec.search_id,
                    rank=rec.rank,
                    train_number=rec.train_number,
                    train_name=rec.train_name,
                    travel_class=rec.travel_class,
                    quota=rec.quota,
                    train_start_date=rec.train_start_date,
                    segment_count=rec.segment_count,
                    status_tier=rec.status_tier,
                    ranking_metadata=rec.ranking_metadata,
                    total_fare=rec.total_fare,
                    currency=rec.currency,
                    fare_complete=rec.fare_complete,
                    created_at=rec.created_at,
                )
                row.segments = [
                    RecommendationSegmentRow(
                        sequence_index=seg.sequence_index,
                        availability_observation_id=seg.observation_id,
                        source_station_code=seg.from_station,
                        destination_station_code=seg.to_station,
                    )
                    for seg in rec.segments
                ]
                session.add(row)

    async def add_provider_usage(self, events: Sequence[ProviderUsageRecord]) -> None:
        if not events:
            return
        async with self._tx() as session:
            session.add_all(
                ProviderUsageRow(
                    id=event.id,
                    provider=event.provider,
                    endpoint=event.endpoint,
                    request_count=event.request_count,
                    status_code=event.status_code,
                    outcome=event.outcome,
                    latency_ms=event.latency_ms,
                    attempt=event.attempt,
                    search_id=event.search_id,
                    created_at=event.created_at,
                )
                for event in events
            )

    # --- Catalog --------------------------------------------------------------------------------
    async def upsert_stations(self, stations: Sequence[Station], *, authoritative: bool) -> None:
        valid = {s.code: s for s in stations if is_valid_station_code(s.code)}
        if not valid:
            return
        async with self._tx() as session:
            await self._upsert_stations(session, list(valid.values()), authoritative=authoritative)

    @staticmethod
    async def _upsert_stations(
        session: AsyncSession, stations: list[Station], *, authoritative: bool
    ) -> None:
        statement = insert(StationRow).values(
            [
                {
                    "id": uuid.uuid4(),
                    "code": s.code,
                    "name": s.name,
                    "city": s.city,
                    "latitude": s.latitude,
                    "longitude": s.longitude,
                }
                for s in stations
            ]
        )
        if authoritative:
            statement = statement.on_conflict_do_update(
                index_elements=["code"],
                set_={
                    "name": statement.excluded.name,
                    "city": statement.excluded.city,
                    "latitude": statement.excluded.latitude,
                    "longitude": statement.excluded.longitude,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=["code"])
        await session.execute(statement)

    async def save_route(self, route: TrainRoute, *, verified: bool, issues: Sequence[str]) -> None:
        version = route_version(route)
        storable_stops = all(is_valid_station_code(stop.station_code) for stop in route.stops)
        async with self._tx() as session:
            await session.execute(
                insert(TrainRow)
                .values(train_number=route.train_number, train_name=route.train_name)
                .on_conflict_do_update(
                    index_elements=["train_number"], set_={"train_name": route.train_name}
                )
            )
            if storable_stops and route.stops:
                stations = {
                    s.station_code: Station(s.station_code, s.station_name or s.station_code)
                    for s in route.stops
                }
                await self._upsert_stations(session, list(stations.values()), authoritative=False)
            existing = await session.scalar(
                select(TrainRouteRow).where(
                    TrainRouteRow.train_number == route.train_number,
                    TrainRouteRow.route_version == version,
                )
            )
            if existing is not None:
                existing.fetched_at = route.fetched_at
                existing.route_verified = verified
                existing.issues = list(issues)
                return
            row = TrainRouteRow(
                train_number=route.train_number,
                route_version=version,
                provider=route.provider,
                fetched_at=route.fetched_at,
                route_verified=verified,
                issues=list(issues),
                classes=list(route.classes) if route.classes is not None else None,
                running_days=route.running_days,
                anomalies=list(route.anomalies),
            )
            if storable_stops:
                row.stops = [
                    TrainStopRow(
                        sequence_index=s.sequence,
                        station_code=s.station_code,
                        station_name=s.station_name,
                        arrival_time=s.arrival_time,
                        departure_time=s.departure_time,
                        day_offset=s.day_offset,
                        halt_minutes=s.halt_minutes,
                        distance_km=s.distance_km,
                        platform=s.platform,
                        is_stoppage=s.is_stoppage,
                    )
                    for s in route.stops
                ]
            session.add(row)

    async def get_recent_route(
        self, train_number: str, *, fetched_after: datetime
    ) -> TrainRoute | None:
        async with self._tx() as session:
            row = await session.scalar(
                select(TrainRouteRow)
                .where(
                    TrainRouteRow.train_number == train_number,
                    TrainRouteRow.fetched_at > fetched_after,
                )
                .order_by(TrainRouteRow.fetched_at.desc())
                .limit(1)
            )
            if row is None or not row.stops:
                return None
            train = await session.get(TrainRow, train_number)
            return TrainRoute(
                train_number=train_number,
                train_name=train.train_name if train else None,
                stops=tuple(
                    TrainStop(
                        sequence=s.sequence_index,
                        station_code=s.station_code,
                        station_name=s.station_name,
                        arrival_time=s.arrival_time,
                        departure_time=s.departure_time,
                        day_offset=s.day_offset,
                        halt_minutes=s.halt_minutes,
                        distance_km=s.distance_km,
                        platform=s.platform,
                        is_stoppage=s.is_stoppage,
                    )
                    for s in row.stops
                ),
                provider=row.provider,
                fetched_at=row.fetched_at,
                classes=tuple(row.classes) if row.classes is not None else None,
                running_days=row.running_days,
                anomalies=tuple(row.anomalies or ()),
            )

    async def ping(self) -> None:
        try:
            await db_session.ping(self._engine)
        except SQLAlchemyError as exc:
            raise PersistenceError(type(exc).__name__) from exc

    async def aclose(self) -> None:
        await self._engine.dispose()
