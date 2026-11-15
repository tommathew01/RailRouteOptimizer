"""Journey optimization request and result (doc 05 §5-6).

The result model is also the persisted snapshot format, so polling clients see the same shape
while a search is running (partial) and after it completes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import ApiModel
from app.schemas.shared import (
    ClassCode,
    DataMode,
    FareOut,
    IgnoredQuota,
    PredictionOut,
    StationCode,
    TrainNumber,
)


class JourneyFilters(ApiModel):
    allow_rac: bool = Field(default=False, description="Include paths with RAC segments.")
    allow_waitlist: bool = Field(
        default=False, description="Include paths with waitlisted segments."
    )


class OptimizeRequest(ApiModel):
    source: StationCode
    destination: StationCode
    journey_date: date = Field(description="Date you depart the source station (IST).")
    classes: list[ClassCode] = Field(min_length=1, max_length=8)
    filters: JourneyFilters = Field(default_factory=JourneyFilters)
    max_segments: int = Field(
        default=4, ge=1, le=10, description="Clamped to the server policy (at most 4)."
    )
    train_numbers: list[TrainNumber] | None = Field(
        default=None, max_length=20, description="Optional: only optimize these trains."
    )
    quota: IgnoredQuota = None

    @field_validator("classes", "train_numbers")
    @classmethod
    def _unique(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else list(dict.fromkeys(value))


class SearchAccepted(ApiModel):
    search_id: uuid.UUID
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    status_url: str


class SearchRequestEcho(ApiModel):
    source: str
    destination: str
    journey_date: date
    classes: list[str]
    quota: Literal["GN"] = "GN"
    filters: JourneyFilters
    max_segments: int
    train_numbers: list[str] | None


class Coverage(ApiModel):
    trains_found: int
    trains_evaluated: int
    combinations_evaluated: int = Field(description="Train x class combinations explored.")
    availability_requests_planned: int = Field(
        description="Requests made + cache hits + requests still needed at the depth reached."
    )
    availability_requests_made: int = Field(description="Provider availability calls (budgeted).")
    request_budget: int
    cache_hits: int
    segments_checked: int = Field(description="Distinct segments with an interpretable answer.")
    segments_unknown: int
    segments_failed: int


class SegmentOut(ApiModel):
    sequence: int
    source: str
    source_name: str | None
    destination: str
    destination_name: str | None
    departure: datetime | None = Field(description="Scheduled departure (IST).")
    arrival: datetime | None = Field(description="Scheduled arrival (IST).")
    provider_query_date: date
    boards_on_later_date: bool = Field(
        description="Boards on a later calendar day than the journey's source departure."
    )
    status: str
    availability_text: str | None
    raw_status: str | None
    waitlist_type: str | None
    waitlist_number: int | None
    rac_number: int | None
    available_count: int | None
    can_book: bool | None
    prediction: PredictionOut | None
    fare: FareOut | None
    checked_at: datetime
    cached: bool
    observation_id: uuid.UUID


class PredictionSummary(ApiModel):
    kind: Literal["MINIMUM_SEGMENT_ESTIMATE"] = "MINIMUM_SEGMENT_ESTIMATE"
    minimum_percentage: float | None
    segments_with_estimate: int
    segments_needing_estimate: int
    note: str = (
        "Lowest provider estimate among RAC/waitlist segments. It is not a probability that the "
        "whole journey will be confirmed."
    )


class RecommendationOut(ApiModel):
    rank: int
    train_number: str
    train_name: str | None
    travel_class: str
    travel_class_label: str
    quota: Literal["GN"] = "GN"
    train_start_date: date
    segment_count: int
    status_tier: int
    status_tier_label: str
    segments: list[SegmentOut]
    total_fare: FareOut | None
    fare_complete: bool
    prediction_summary: PredictionSummary
    explanation: list[str]
    booking_steps: list[str]
    oldest_checked_at: datetime


class ClassEvaluation(ApiModel):
    travel_class: str
    state: Literal["SOLVED", "EXHAUSTED", "STOPPED", "ACTIVE", "NOT_OFFERED", "NOT_EVALUATED"]
    depth_reached: int
    best_status_tier: int | None
    recommendations: int


class TrainEvaluation(ApiModel):
    train_number: str
    train_name: str | None
    evaluation: Literal[
        "EVALUATED",
        "ROUTE_UNVERIFIED",
        "ROUTE_UNAVAILABLE",
        "DIFFERENT_STATIONS",
        "NOT_IN_TRAIN_SEARCH",
        "SKIPPED_TRAIN_LIMIT",
    ]
    route_issues: list[str]
    departure: datetime | None
    arrival: datetime | None
    intermediate_stops_total: int
    intermediate_stops_considered: int
    classes: list[ClassEvaluation]


class SearchError(ApiModel):
    code: str
    message: str


class JourneySearchResponse(ApiModel):
    search_id: uuid.UUID
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    status_url: str
    data_mode: DataMode
    provider: str
    request: SearchRequestEcho
    search_completeness: str | None
    incomplete_reason: str | None
    coverage: Coverage | None
    trains: list[TrainEvaluation]
    recommendations: list[RecommendationOut]
    warnings: list[str]
    error: SearchError | None = None
    stale_after_seconds: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
