"""Direct segment availability check (doc 05 §4). Quota is never accepted from the client."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.shared import (
    AvailabilityOut,
    ClassCode,
    DataMode,
    FareOut,
    IgnoredQuota,
    PredictionOut,
    StationCode,
    TrainNumber,
)


class AvailabilityCheckRequest(ApiModel):
    train_number: TrainNumber
    source: StationCode
    destination: StationCode
    journey_date: date = Field(description="Date you depart the segment's source station (IST).")
    travel_class: ClassCode
    quota: IgnoredQuota = None


class AvailabilityCheckResponse(ApiModel):
    train_number: str
    source: str
    destination: str
    journey_date: date
    provider_query_date: date = Field(description="Date sent to the provider (see date policy).")
    train_start_date: date
    travel_class: str
    quota: str = "GN"
    availability: AvailabilityOut
    prediction: PredictionOut | None
    fare: FareOut | None
    provider: str
    provider_checked_at: datetime | None
    checked_at: datetime
    cached: bool
    anomalies: list[str]
    data_mode: DataMode
    warnings: list[str]
