from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.database.models import (
    AvailabilityObservationRow,
    ProviderUsageRow,
    RecommendationSegmentRow,
    StationRow,
    TrainStopRow,
)
from app.domain.enums import (
    AvailabilityStatus,
    IncompleteReason,
    SearchCompleteness,
    SearchStatus,
    SegmentQueryOutcome,
)
from app.domain.models import (
    AvailabilityRecord,
    Fare,
    Prediction,
    PredictionSource,
    SegmentKey,
    SegmentObservation,
    Station,
    TrainRoute,
    TrainStop,
)
from app.repositories.records import (
    ProviderUsageRecord,
    RecommendationRecord,
    RecommendationSegmentRecord,
    SearchRecord,
    SegmentRunRecord,
)
from app.repositories.sqlalchemy import SqlAlchemyPersistence
from tests.integration.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]
NOW = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)
KEY = SegmentKey("12345", date(2026, 11, 20), "TIR", "SRR", "3A")


def search_record() -> SearchRecord:
    return SearchRecord(
        id=uuid.uuid4(),
        source="TIR",
        destination="TVC",
        journey_date=date(2026, 11, 20),
        classes=["3A"],
        filters={"allow_rac": True, "allow_waitlist": False},
        train_numbers=None,
        max_segments=4,
        request_budget=30,
        provider="RAILKIT",
        created_at=NOW,
    )


def observation() -> SegmentObservation:
    return SegmentObservation(
        id=uuid.uuid4(),
        key=KEY,
        provider_date=date(2026, 11, 20),
        record=AvailabilityRecord(
            status=AvailabilityStatus.WAITLIST,
            provider="RAILKIT",
            raw_status="RLWL31/WL23",
            availability_text="WL 23",
            waitlist_type="RLWL",
            waitlist_number=23,
            can_book=True,
            prediction=Prediction("RAILKIT", "73% Chance", 73.0, PredictionSource.FIELD),
            fare=Fare(Decimal("1670.00"), "INR", "RAILKIT_SEAT_AVAILABILITY_TOTAL_FARE"),
            raw_payload={"availability": [{"rawStatus": "RLWL31/WL23"}]},
        ),
        observed_at=NOW,
    )


async def test_search_lifecycle_round_trip(persistence: SqlAlchemyPersistence) -> None:
    search = search_record()
    await persistence.create_search(search)
    search.status = SearchStatus.COMPLETED
    search.search_completeness = SearchCompleteness.PARTIAL_BUDGET
    search.incomplete_reason = IncompleteReason.AVAILABILITY_REQUEST_BUDGET_REACHED
    search.requests_made, search.cache_hits = 30, 4
    search.result_snapshot = {"recommendations": []}
    search.completed_at = search.updated_at = NOW + timedelta(seconds=20)
    await persistence.save_search(search)
    loaded = await persistence.get_search(search.id)
    assert loaded is not None
    assert loaded.status is SearchStatus.COMPLETED
    assert loaded.search_completeness is SearchCompleteness.PARTIAL_BUDGET
    assert loaded.requests_made == 30
    assert loaded.result_snapshot == {"recommendations": []}
    assert await persistence.get_search(uuid.uuid4()) is None


async def test_selected_quotas_and_quota_completeness_round_trip(
    persistence: SqlAlchemyPersistence,
) -> None:
    search = search_record()
    search.quotas = ["GN", "TQ"]
    await persistence.create_search(search)
    search.search_completeness = SearchCompleteness.PARTIAL_QUOTA_NOT_QUERIED
    search.incomplete_reason = IncompleteReason.QUOTA_NOT_QUERIED
    await persistence.save_search(search)
    loaded = await persistence.get_search(search.id)
    assert loaded is not None
    assert (loaded.quotas, loaded.quota) == (["GN", "TQ"], "GN")
    assert loaded.search_completeness is SearchCompleteness.PARTIAL_QUOTA_NOT_QUERIED
    assert loaded.incomplete_reason is IncompleteReason.QUOTA_NOT_QUERIED
    legacy = search_record()  # rows written before quota selection default to General
    await persistence.create_search(legacy)
    assert (await persistence.get_search(legacy.id)).quotas == ["GN"]  # type: ignore[union-attr]


async def test_unfinished_searches_are_failed_on_restart(
    persistence: SqlAlchemyPersistence,
) -> None:
    running = search_record()
    running.status = SearchStatus.RUNNING
    await persistence.create_search(running)
    await persistence.save_search(running)
    fresh = search_record()
    fresh.status = SearchStatus.RUNNING
    await persistence.create_search(fresh)
    fresh.updated_at = NOW + timedelta(minutes=10)  # still making progress (another replica)
    await persistence.save_search(fresh)
    reaped = await persistence.fail_unfinished_searches(
        error_code="INTERRUPTED",
        now=NOW + timedelta(minutes=11),
        stale_before=NOW + timedelta(minutes=5),
    )
    assert reaped == 1
    still_running = await persistence.get_search(fresh.id)
    assert still_running is not None
    assert still_running.status is SearchStatus.RUNNING
    loaded = await persistence.get_search(running.id)
    assert loaded is not None
    assert loaded.status is SearchStatus.FAILED
    assert loaded.error_code == "INTERRUPTED"


async def test_observations_runs_recommendations_and_usage(
    persistence: SqlAlchemyPersistence,
) -> None:
    search = search_record()
    await persistence.create_search(search)
    obs = observation()
    await persistence.add_observations([obs, obs])  # append-only and idempotent per id
    await persistence.add_segment_runs(
        [
            SegmentRunRecord(
                uuid.uuid4(),
                search.id,
                KEY,
                KEY.train_start_date,
                SegmentQueryOutcome.SUCCESS,
                False,
                NOW,
                120.0,
                observation_id=obs.id,
            ),
            SegmentRunRecord(
                uuid.uuid4(),
                search.id,
                KEY,
                KEY.train_start_date,
                SegmentQueryOutcome.PROVIDER_TIMEOUT,
                False,
                NOW,
                error_code="PROVIDER_TIMEOUT",
            ),
        ]
    )
    await persistence.save_recommendations(
        [
            RecommendationRecord(
                id=uuid.uuid4(),
                search_id=search.id,
                rank=1,
                train_number="12345",
                train_name="TEST",
                travel_class="3A",
                quota="GN",
                train_start_date=KEY.train_start_date,
                segment_count=1,
                status_tier=2,
                fare_complete=True,
                created_at=NOW,
                segments=(RecommendationSegmentRecord(0, "TIR", "SRR", obs.id),),
                ranking_metadata={"prediction_floor": 73.0},
                total_fare=Decimal("1670.00"),
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
                120.0,
                search.id,
            )
        ]
    )
    async with persistence._sessions() as session:
        row = await session.scalar(select(AvailabilityObservationRow))
        assert row is not None
        assert row.prediction_percentage == Decimal("73.00")
        assert row.raw_status == "RLWL31/WL23"
        assert row.raw_payload == {"availability": [{"rawStatus": "RLWL31/WL23"}]}
        assert (
            await session.scalar(select(func.count()).select_from(AvailabilityObservationRow)) == 1
        )
        assert await session.scalar(select(func.count()).select_from(RecommendationSegmentRow)) == 1
        assert await session.scalar(select(func.count()).select_from(ProviderUsageRow)) == 1


async def test_station_upsert_authority(persistence: SqlAlchemyPersistence) -> None:
    await persistence.upsert_stations([Station("TIR", "TIRUR")], authoritative=False)
    await persistence.upsert_stations(
        [Station("TIR", "Tirur", "Tirur", 10.9, 75.9)], authoritative=True
    )
    await persistence.upsert_stations([Station("TIR", "TIRUR AGAIN")], authoritative=False)
    async with persistence._sessions() as session:
        name = await session.scalar(select(StationRow.name).where(StationRow.code == "TIR"))
    assert name == "Tirur"


async def test_route_save_and_recent_lookup(persistence: SqlAlchemyPersistence) -> None:
    route = TrainRoute(
        "12345",
        "TEST EXPRESS",
        (
            TrainStop(0, "TIR", "TIRUR", None, time(21, 5), 0, 0, 0.0, "1"),
            TrainStop(1, "SRR", "SHORANUR JN", time(23, 58), time(0, 8), 0, 10, 45.0),
            TrainStop(2, "TVC", "TRIVANDRUM", time(6, 5), None, 1, None, 300.0),
        ),
        "RAILKIT",
        NOW,
        classes=("3A", "SL"),
    )
    await persistence.save_route(route, verified=True, issues=[])
    await persistence.save_route(route, verified=True, issues=[])  # same version: refresh only
    loaded = await persistence.get_recent_route("12345", fetched_after=NOW - timedelta(hours=1))
    assert loaded is not None
    assert [s.station_code for s in loaded.stops] == ["TIR", "SRR", "TVC"]
    assert loaded.stops[1].departure_time == time(0, 8)
    assert loaded.classes == ("3A", "SL")
    assert await persistence.get_recent_route("12345", fetched_after=NOW) is None
    async with persistence._sessions() as session:
        assert await session.scalar(select(func.count()).select_from(TrainStopRow)) == 3
