"""Direct segment availability check (doc 05 §4), for one quota (General by default)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.shared import (
    AvailabilityOut,
    ClassCode,
    DataMode,
    FareOut,
    PredictionOut,
    QuotaCode,
    QuotaEligibilityOut,
    QuotaLiteral,
    StationCode,
    TrainNumber,
)


class AvailabilityCheckRequest(ApiModel):
    train_number: TrainNumber
    source: StationCode
    destination: StationCode
    journey_date: date = Field(description="Date you depart the segment's source station (IST).")
    travel_class: ClassCode
    quota: QuotaCode | None = Field(
        default=None,
        description=(
            "GN (default) or TQ. Tatkal is only queried once its booking "
            "window is open; otherwise the response has queried=false and no availability."
        ),
    )


class AvailabilityCheckResponse(ApiModel):
    train_number: str
    source: str
    destination: str
    journey_date: date
    provider_query_date: date = Field(description="Date sent to the provider (see date policy).")
    train_start_date: date | None = Field(
        description="Date the train leaves its origin station; null only if never determined."
    )
    travel_class: str
    quota: QuotaLiteral = "GN"
    quota_label: str = "General"
    queried: bool = Field(
        default=True,
        description="False when the provider was not asked (see eligibility). Never 'unavailable'.",
    )
    eligibility: QuotaEligibilityOut | None = None
    availability: AvailabilityOut | None = Field(description="Null only when queried is false.")
    prediction: PredictionOut | None
    fare: FareOut | None
    provider: str
    provider_checked_at: datetime | None
    checked_at: datetime | None = Field(description="Null only when queried is false.")
    cached: bool
    anomalies: list[str]
    data_mode: DataMode
    warnings: list[str]
