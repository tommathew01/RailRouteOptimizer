"""Provider-independent domain models (stdlib only).

Times are IST wall-clock values. ``TrainStop.day_offset`` is 0 for the train's originating day.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.domain.enums import AvailabilityStatus, Quota

STATION_CODE_PATTERN = re.compile(r"^[A-Z0-9]{1,5}$")
TRAIN_NUMBER_PATTERN = re.compile(r"^\d{5}$")


def is_valid_station_code(value: str) -> bool:
    return bool(STATION_CODE_PATTERN.fullmatch(value))


def is_valid_train_number(value: str) -> bool:
    return bool(TRAIN_NUMBER_PATTERN.fullmatch(value))


@dataclass(frozen=True, slots=True)
class Station:
    code: str
    name: str
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True, slots=True)
class TrainSummary:
    """A train returned by "trains between stations" for the requested pair and date."""

    train_number: str
    train_name: str | None
    from_station_code: str
    to_station_code: str
    from_station_name: str | None = None
    to_station_name: str | None = None
    origin_station_code: str | None = None
    terminus_station_code: str | None = None
    departure_time: time | None = None
    arrival_time: time | None = None
    duration_minutes: int | None = None
    running_days: str | None = None
    distance_km: int | None = None
    halts: int | None = None


@dataclass(frozen=True, slots=True)
class TrainStop:
    sequence: int
    station_code: str
    station_name: str | None
    arrival_time: time | None
    departure_time: time | None
    day_offset: int | None
    halt_minutes: int | None = None
    distance_km: float | None = None
    platform: str | None = None
    is_stoppage: bool | None = None


@dataclass(frozen=True, slots=True)
class TrainRoute:
    train_number: str
    train_name: str | None
    stops: tuple[TrainStop, ...]
    provider: str
    fetched_at: datetime
    #: Classes the provider lists for this train; ``None`` when the provider did not say.
    classes: tuple[str, ...] | None = None
    running_days: str | None = None
    anomalies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AvailabilityQuery:
    """One provider availability request. ``journey_date`` is the date *sent to the provider*."""

    train_number: str
    from_station: str
    to_station: str
    journey_date: date
    travel_class: str
    quota: Quota = Quota.GENERAL


class PredictionSource(StrEnum):
    FIELD = "FIELD"
    TEXT = "TEXT"


@dataclass(frozen=True, slots=True)
class Prediction:
    """Provider estimate. Never changes, and is never derived from, the current status."""

    provider: str
    text: str | None
    percentage: float | None
    percentage_source: PredictionSource | None = None


@dataclass(frozen=True, slots=True)
class Fare:
    amount: Decimal
    currency: str
    basis: str


@dataclass(frozen=True, slots=True)
class AvailabilityRecord:
    """Normalized provider answer for one :class:`AvailabilityQuery`."""

    status: AvailabilityStatus
    provider: str
    raw_status: str | None = None
    availability_text: str | None = None
    provider_status: str | None = None
    waitlist_type: str | None = None
    waitlist_number: int | None = None
    rac_number: int | None = None
    available_count: int | None = None
    can_book: bool | None = None
    prediction: Prediction | None = None
    fare: Fare | None = None
    provider_checked_at: datetime | None = None
    anomalies: tuple[str, ...] = ()
    raw_payload: Mapping[str, Any] | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class SegmentKey:
    """Canonical identity of a segment (doc 04 §2). ``train_start_date`` is the train's
    originating date, shared by every segment of one train run (decision D-01)."""

    train_number: str
    train_start_date: date
    from_station: str
    to_station: str
    travel_class: str
    quota: Quota = Quota.GENERAL


@dataclass(frozen=True, slots=True)
class SegmentObservation:
    """An immutable, timestamped provider answer for one segment."""

    id: UUID
    key: SegmentKey
    provider_date: date
    record: AvailabilityRecord
    observed_at: datetime
