"""Field types and blocks shared by several endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, PlainSerializer, StringConstraints

from app.domain.models import AvailabilityRecord, Fare, Prediction
from app.schemas.common import ApiModel


def _upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


StationCode = Annotated[
    str,
    BeforeValidator(_upper),
    StringConstraints(pattern=r"^[A-Z0-9]{1,5}$"),
    Field(description="Station code (1-5 letters/digits).", examples=["TIR"]),
]
TrainNumber = Annotated[
    str,
    BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^\d{5}$"),
    Field(description="Five-digit train number.", examples=["12345"]),
]
ClassCode = Annotated[
    str,
    BeforeValidator(_upper),
    StringConstraints(pattern=r"^[0-9A-Z]{2}$"),
    Field(description="Travel class code.", examples=["3A"]),
]
Money = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str)]
DataMode = Literal["DEMO", "LIVE"]
IgnoredQuota = Annotated[
    str | None,
    Field(
        default=None,
        description="Ignored. General quota (GN) is always enforced by the server.",
        json_schema_extra={"deprecated": True},
    ),
]


class AvailabilityOut(ApiModel):
    status: str = Field(description="Normalized current status. Never derived from a prediction.")
    availability_text: str | None
    raw_status: str | None = Field(description="Exact provider status string.")
    provider_status: str | None
    waitlist_type: str | None
    waitlist_number: int | None
    rac_number: int | None
    available_count: int | None
    can_book: bool | None = Field(description="Provider flag. Bookable does not mean confirmed.")

    @classmethod
    def of(cls, record: AvailabilityRecord) -> AvailabilityOut:
        return cls(
            status=record.status.value,
            availability_text=record.availability_text,
            raw_status=record.raw_status,
            provider_status=record.provider_status,
            waitlist_type=record.waitlist_type,
            waitlist_number=record.waitlist_number,
            rac_number=record.rac_number,
            available_count=record.available_count,
            can_book=record.can_book,
        )


class PredictionOut(ApiModel):
    provider: str
    label: str = Field(description="UI label, e.g. 'RailKit prediction'. Not a guarantee.")
    text: str | None = Field(description="Exact provider text.")
    percentage: float | None
    percentage_source: Literal["FIELD", "TEXT"] | None

    @classmethod
    def of(cls, prediction: Prediction | None) -> PredictionOut | None:
        if prediction is None:
            return None
        label = "RailKit prediction" if prediction.provider == "RAILKIT" else "Demo estimate"
        return cls(
            provider=prediction.provider,
            label=label,
            text=prediction.text,
            percentage=prediction.percentage,
            percentage_source=(
                prediction.percentage_source.value if prediction.percentage_source else None
            ),
        )


class FareOut(ApiModel):
    amount: Money
    currency: str
    basis: str | None = None

    @classmethod
    def of(cls, fare: Fare | None) -> FareOut | None:
        return (
            None
            if fare is None
            else cls(amount=fare.amount, currency=fare.currency, basis=fare.basis)
        )


class TimestampedOut(ApiModel):
    checked_at: datetime = Field(description="When RailRoute received the provider answer (UTC).")
    provider_checked_at: datetime | None = Field(
        default=None, description="Provider's own check time, when supplied (RailKit: never)."
    )


class DatePair(ApiModel):
    journey_date: date
    provider_query_date: date
