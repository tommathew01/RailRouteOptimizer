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
    EligibilityState,
    FareOut,
    IgnoredQuota,
    PredictionOut,
    QuotaCode,
    QuotaEligibilityOut,
    QuotaLiteral,
    StationCode,
    TrainNumber,
)


def _general_only() -> list[QuotaLiteral]:
    return ["GN"]


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
        default=None,
        min_length=1,
        max_length=20,
        description="Optional: only these trains (omit for all; an empty list is refused).",
    )
    quotas: list[QuotaCode] = Field(
        default_factory=_general_only,
        min_length=1,
        max_length=2,
        description=(
            "Quotas to search; each is optimized separately and never mixed within a journey. "
            "Tatkal is only queried once its booking window is open."
        ),
    )
    quota: IgnoredQuota = None

    @field_validator("classes", "train_numbers", "quotas")
    @classmethod
    def _unique(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else list(dict.fromkeys(value))


class PlannedCombination(ApiModel):
    train_number: str
    travel_class: str
    quota: QuotaLiteral


class PlanQuota(ApiModel):
    quota: QuotaLiteral
    quota_label: str
    combinations: int = Field(description="Combinations of this quota the search will query.")
    combinations_not_queried: int = Field(
        description="Offered combinations not queried now (e.g. Tatkal booking not open yet)."
    )
    next_opening_at: datetime | None = Field(
        description="Earliest future booking window opening among the skipped ones (IST)."
    )
    notes: list[str]


class PlanTrain(ApiModel):
    train_number: str
    train_name: str | None
    evaluation: str = Field(description="EVALUATED, or why the train cannot be checked.")
    combinations: int


class SearchPlanResponse(ApiModel):
    """What a search started now would query — no availability request was made (D-29)."""

    data_mode: DataMode
    request_budget: int = Field(description="Provider availability attempts allowed per search.")
    max_segments: int
    trains_selected: int
    trains_evaluated: int
    combinations: int = Field(description="Train x class x eligible quota combinations to query.")
    combinations_not_queried: int
    classes_not_offered: int = Field(description="Selected train x class pairs not offered.")
    requests_per_combination: float | None = Field(
        description="Budget divided by combinations: the average depth each one can get."
    )
    covers_direct_checks: bool = Field(
        description="True when the budget pays for every combination's direct-ticket check."
    )
    planned: list[PlannedCombination]
    quotas: list[PlanQuota]
    trains: list[PlanTrain]
    explanation: list[str]


class SearchAccepted(ApiModel):
    search_id: uuid.UUID
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    status_url: str


class SearchRequestEcho(ApiModel):
    source: str
    destination: str
    journey_date: date
    classes: list[str]
    quota: QuotaLiteral = Field(default="GN", description="Deprecated: the first of `quotas`.")
    quotas: list[QuotaLiteral] = Field(default_factory=_general_only)
    filters: JourneyFilters
    max_segments: int
    train_numbers: list[str] | None


class Coverage(ApiModel):
    trains_found: int
    trains_evaluated: int
    combinations_evaluated: int = Field(description="Train x class x quota combinations explored.")
    combinations_not_queried: int = Field(
        default=0,
        description="Offered combinations deliberately not queried (e.g. Tatkal not open yet).",
    )
    combinations_not_reached: int = Field(
        default=0,
        description=(
            "Queryable combinations that received no availability check at all (budget, "
            "deadline or provider stop). Zero whenever the budget covers every direct check."
        ),
    )
    availability_requests_planned: int = Field(
        description="Requests made + cache hits + requests still needed at the depth reached."
    )
    availability_requests_made: int = Field(
        description="Provider availability attempts charged to the budget, retries included."
    )
    availability_checks_made: int = Field(
        default=0,
        description="Logical availability checks sent to the provider (not cache hits).",
    )
    availability_retries: int = Field(
        default=0, description="Retry attempts included in availability_requests_made."
    )
    availability_retries_refused: int = Field(
        default=0,
        description="Failed checks not retried because the search budget was used up.",
    )
    request_budget: int = Field(description="Provider availability attempts allowed per search.")
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
    quota: QuotaLiteral = "GN"
    quota_label: str = "General"
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
    """One train x class x quota. Not-queried quotas are never reported as unavailable."""

    travel_class: str
    quota: QuotaLiteral = "GN"
    quota_label: str = "General"
    state: Literal[
        "SOLVED",
        "EXHAUSTED",
        "STOPPED",
        "ACTIVE",
        "NOT_OFFERED",
        "NOT_EVALUATED",
        "NOT_YET_OPEN",
        "QUOTA_NOT_SUPPORTED",
        "NOT_QUERIED",
    ]
    queried: bool = Field(default=True, description="False when the provider was not asked.")
    segments_queried: int = Field(
        default=0, description="Segment availability answers for this combination (incl. cache)."
    )
    depth_reached: int
    best_status_tier: int | None
    recommendations: int
    eligibility: QuotaEligibilityOut | None = None


class QuotaSkipGroup(ApiModel):
    state: EligibilityState
    combinations: int
    travel_classes: list[str]
    opens_at: datetime | None = Field(description="Earliest booking window opening (IST).")
    message: str


class QuotaSummary(ApiModel):
    """Per-quota completeness. ``queried`` is False when the provider was never asked."""

    quota: QuotaLiteral
    quota_label: str
    provider_supported: bool
    queried: bool
    combinations_eligible: int = Field(description="Combinations whose booking window allowed it.")
    combinations_not_queried: int
    next_opening_at: datetime | None = Field(
        description="Earliest future booking window opening among skipped combinations (IST)."
    )
    not_queried: list[QuotaSkipGroup]
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
    quotas: list[QuotaSummary] = Field(default_factory=list)
    recommendations: list[RecommendationOut]
    warnings: list[str]
    error: SearchError | None = None
    stale_after_seconds: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
