from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.cli import purge
from app.database.models import (
    AvailabilityObservationRow,
    JourneySearchRow,
    ProviderUsageRow,
    RecommendationRow,
    SegmentQueryRunRow,
)
from app.domain.enums import SearchStatus, SegmentQueryOutcome
from app.repositories.records import (
    ProviderUsageRecord,
    RecommendationRecord,
    RecommendationSegmentRecord,
    SegmentRunRecord,
)
from app.repositories.sqlalchemy import SqlAlchemyPersistence
from tests.integration.conftest import requires_db
from tests.integration.test_postgres_persistence import KEY, NOW, observation, search_record

pytestmark = [pytest.mark.integration, requires_db]


async def _count(gateway: SqlAlchemyPersistence, table: type) -> int:
    async with gateway._sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(table)) or 0)


async def test_retention_policy(persistence: SqlAlchemyPersistence) -> None:
    finished, running = search_record(), search_record()
    finished.status, running.status = SearchStatus.COMPLETED, SearchStatus.RUNNING
    for search in (finished, running):
        await persistence.create_search(search)
        await persistence.save_search(search)
    referenced, orphan = observation(), observation()
    await persistence.add_observations([referenced, orphan])
    await persistence.add_segment_runs(
        [
            SegmentRunRecord(
                uuid.uuid4(),
                finished.id,
                KEY,
                KEY.train_start_date,
                SegmentQueryOutcome.SUCCESS,
                False,
                NOW,
                observation_id=referenced.id,
            )
        ]
    )
    await persistence.save_recommendations(
        [
            RecommendationRecord(
                id=uuid.uuid4(),
                search_id=finished.id,
                rank=1,
                train_number="12345",
                train_name=None,
                travel_class="3A",
                quota="GN",
                train_start_date=KEY.train_start_date,
                segment_count=1,
                status_tier=2,
                fare_complete=True,
                created_at=NOW,
                segments=(RecommendationSegmentRecord(0, "TIR", "SRR", referenced.id),),
                total_fare=Decimal("100.00"),
                currency="INR",
            )
        ]
    )
    await persistence.add_provider_usage(
        [
            ProviderUsageRecord(
                uuid.uuid4(),
                "RAILKIT",
                "seat_availability",
                "SUCCESS",
                1,
                NOW,
                200,
                10.0,
                finished.id,
            )
        ]
    )
    engine = persistence._engine
    policy = {"raw_payload_days": 14, "search_days": 90, "usage_days": 400}

    # Day 20: only raw payloads are past retention.
    preview = await purge(engine, now=NOW + timedelta(days=20), dry_run=True, **policy)
    assert preview.payloads_stripped == 2
    assert preview.searches_deleted == 0
    first = await purge(engine, now=NOW + timedelta(days=20), dry_run=False, **policy)
    assert first.payloads_stripped == 2
    assert (first.searches_deleted, first.observations_deleted, first.usage_rows_deleted) == (
        0,
        0,
        0,
    )
    async with persistence._sessions() as session:
        payloads = (await session.scalars(select(AvailabilityObservationRow.raw_payload))).all()
    assert payloads == [None, None]

    # Day 100: the finished search and every unreferenced observation go; running search stays.
    second = await purge(engine, now=NOW + timedelta(days=100), dry_run=False, **policy)
    assert second.searches_deleted == 1
    assert second.observations_deleted == 2  # the orphan + the one its recommendation used
    assert second.usage_rows_deleted == 0
    assert await _count(persistence, JourneySearchRow) == 1
    assert await _count(persistence, RecommendationRow) == 0
    assert await _count(persistence, SegmentQueryRunRow) == 0
    assert await _count(persistence, ProviderUsageRow) == 1  # kept for billing, search_id nulled
    remaining = await persistence.get_search(running.id)
    assert remaining is not None

    third = await purge(engine, now=NOW + timedelta(days=401), dry_run=False, **policy)
    assert third.usage_rows_deleted == 1


async def test_retention_rejects_zero_day_policies(persistence: SqlAlchemyPersistence) -> None:
    with pytest.raises(ValueError, match="at least one day"):
        await purge(
            persistence._engine,
            now=NOW,
            raw_payload_days=0,
            search_days=90,
            usage_days=400,
            dry_run=True,
        )
