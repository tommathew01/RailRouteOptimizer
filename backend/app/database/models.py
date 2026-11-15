"""PostgreSQL schema (doc 06 §1-2). Observations, runs and usage rows are append-only."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

JSON = dict[str, Any]


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class StationRow(Base):
    __tablename__ = "stations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    city: Mapped[str | None] = mapped_column(String(120))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[JSON | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class TrainRow(Base):
    __tablename__ = "trains"

    train_number: Mapped[str] = mapped_column(String(5), primary_key=True)
    train_name: Mapped[str | None] = mapped_column(String(160))
    metadata_json: Mapped[JSON | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = _now()


class TrainRouteRow(Base):
    __tablename__ = "train_routes"
    __table_args__ = (UniqueConstraint("train_number", "route_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    train_number: Mapped[str] = mapped_column(ForeignKey("trains.train_number", ondelete="CASCADE"))
    route_version: Mapped[str] = mapped_column(String(64))
    journey_date: Mapped[date | None] = mapped_column(Date)
    provider: Mapped[str] = mapped_column(String(20))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    route_verified: Mapped[bool] = mapped_column(Boolean)
    issues: Mapped[list[str]] = mapped_column(JSONB, default=list)
    classes: Mapped[list[str] | None] = mapped_column(JSONB)
    running_days: Mapped[str | None] = mapped_column(String(16))
    anomalies: Mapped[list[str]] = mapped_column(JSONB, default=list)

    stops: Mapped[list[TrainStopRow]] = relationship(
        back_populates="route",
        order_by="TrainStopRow.sequence_index",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TrainStopRow(Base):
    __tablename__ = "train_stops"
    __table_args__ = (UniqueConstraint("route_id", "sequence_index"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("train_routes.id", ondelete="CASCADE"))
    sequence_index: Mapped[int] = mapped_column(Integer)
    station_code: Mapped[str] = mapped_column(ForeignKey("stations.code"))
    station_name: Mapped[str | None] = mapped_column(String(160))
    arrival_time: Mapped[time | None] = mapped_column(Time)
    departure_time: Mapped[time | None] = mapped_column(Time)
    day_offset: Mapped[int | None] = mapped_column(SmallInteger)
    halt_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    distance_km: Mapped[float | None] = mapped_column(Float)
    platform: Mapped[str | None] = mapped_column(String(16))
    is_stoppage: Mapped[bool | None] = mapped_column(Boolean)

    route: Mapped[TrainRouteRow] = relationship(back_populates="stops")


class JourneySearchRow(Base):
    __tablename__ = "journey_searches"
    __table_args__ = (
        Index("ix_journey_searches_created_at_desc", text("created_at DESC")),
        Index("ix_journey_searches_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source_station_code: Mapped[str] = mapped_column(String(8))
    destination_station_code: Mapped[str] = mapped_column(String(8))
    journey_date: Mapped[date] = mapped_column(Date)
    classes: Mapped[list[str]] = mapped_column(JSONB)
    quota: Mapped[str] = mapped_column(String(4), default="GN", server_default="GN")
    filters: Mapped[JSON] = mapped_column(JSONB)
    train_numbers: Mapped[list[str] | None] = mapped_column(JSONB)
    max_segments: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(16))
    search_completeness: Mapped[str | None] = mapped_column(String(32))
    incomplete_reason: Mapped[str | None] = mapped_column(String(64))
    request_budget: Mapped[int] = mapped_column(Integer)
    requests_made: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_hits: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    provider: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(64))
    result_snapshot: Mapped[JSON | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()


class AvailabilityObservationRow(Base):
    __tablename__ = "availability_observations"
    __table_args__ = (
        Index(
            "ix_availability_observations_identity",
            "train_number",
            "journey_date",
            "source_station_code",
            "destination_station_code",
            "travel_class",
            "quota",
            text("observed_at DESC"),
        ),
        Index("ix_availability_observations_observed_at", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    train_number: Mapped[str] = mapped_column(String(5))
    train_start_date: Mapped[date] = mapped_column(Date)
    journey_date: Mapped[date] = mapped_column(Date)  # date sent to the provider
    source_station_code: Mapped[str] = mapped_column(String(8))
    destination_station_code: Mapped[str] = mapped_column(String(8))
    travel_class: Mapped[str] = mapped_column(String(4))
    quota: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(16))
    availability_text: Mapped[str | None] = mapped_column(String(120))
    raw_status: Mapped[str | None] = mapped_column(String(120))
    provider_status: Mapped[str | None] = mapped_column(String(60))
    waitlist_type: Mapped[str | None] = mapped_column(String(8))
    waitlist_number: Mapped[int | None] = mapped_column(Integer)
    rac_number: Mapped[int | None] = mapped_column(Integer)
    available_count: Mapped[int | None] = mapped_column(Integer)
    can_book: Mapped[bool | None] = mapped_column(Boolean)
    prediction_text: Mapped[str | None] = mapped_column(String(200))
    prediction_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    prediction_percentage_source: Mapped[str | None] = mapped_column(String(8))
    fare_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    fare_basis: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(20))
    provider_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    anomalies: Mapped[list[str]] = mapped_column(JSONB, default=list)
    raw_payload: Mapped[JSON | None] = mapped_column(JSONB)


class SegmentQueryRunRow(Base):
    __tablename__ = "segment_query_runs"
    __table_args__ = (Index("ix_segment_query_runs_search_outcome", "search_id", "outcome"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    search_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journey_searches.id", ondelete="CASCADE")
    )
    train_number: Mapped[str] = mapped_column(String(5))
    train_start_date: Mapped[date] = mapped_column(Date)
    journey_date: Mapped[date] = mapped_column(Date)
    source_station_code: Mapped[str] = mapped_column(String(8))
    destination_station_code: Mapped[str] = mapped_column(String(8))
    travel_class: Mapped[str] = mapped_column(String(4))
    quota: Mapped[str] = mapped_column(String(4))
    outcome: Mapped[str] = mapped_column(String(32))
    provider_latency_ms: Mapped[float | None] = mapped_column(Float)
    cache_hit: Mapped[bool] = mapped_column(Boolean)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(300))
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("availability_observations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecommendationRow(Base):
    __tablename__ = "recommendations"
    __table_args__ = (Index("ix_recommendations_search_rank", "search_id", "rank"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    search_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journey_searches.id", ondelete="CASCADE")
    )
    rank: Mapped[int] = mapped_column(Integer)
    train_number: Mapped[str] = mapped_column(String(5))
    train_name: Mapped[str | None] = mapped_column(String(160))
    travel_class: Mapped[str] = mapped_column(String(4))
    quota: Mapped[str] = mapped_column(String(4))
    train_start_date: Mapped[date] = mapped_column(Date)
    segment_count: Mapped[int] = mapped_column(SmallInteger)
    status_tier: Mapped[int] = mapped_column(SmallInteger)
    ranking_metadata: Mapped[JSON] = mapped_column(JSONB)
    total_fare: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    fare_complete: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    segments: Mapped[list[RecommendationSegmentRow]] = relationship(
        back_populates="recommendation",
        order_by="RecommendationSegmentRow.sequence_index",
        cascade="all, delete-orphan",
    )


class RecommendationSegmentRow(Base):
    __tablename__ = "recommendation_segments"
    __table_args__ = (UniqueConstraint("recommendation_id", "sequence_index"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE")
    )
    sequence_index: Mapped[int] = mapped_column(SmallInteger)
    availability_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("availability_observations.id")
    )
    source_station_code: Mapped[str] = mapped_column(String(8))
    destination_station_code: Mapped[str] = mapped_column(String(8))

    recommendation: Mapped[RecommendationRow] = relationship(back_populates="segments")


class ProviderUsageRow(Base):
    __tablename__ = "provider_usage"
    __table_args__ = (Index("ix_provider_usage_provider_created", "provider", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    endpoint: Mapped[str] = mapped_column(String(40))
    request_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    outcome: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    attempt: Mapped[int] = mapped_column(SmallInteger)
    search_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journey_searches.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
