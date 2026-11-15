"""Field types and blocks shared by several endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, PlainSerializer, StringConstraints

from app.domain.models import AvailabilityRecord, Fare, Prediction
from app.domain.quota_eligibility import QuotaEligibility, describe_eligibility
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
        description="Deprecated and ignored (predates quota selection). Use `quotas`.",
        json_schema_extra={"deprecated": True},
    ),
]
QuotaLiteral = Literal["GN", "TQ"]
QuotaCode = Annotated[
    QuotaLiteral,
    BeforeValidator(_upper),
    Field(
        description="Reservation quota: GN (General) or TQ (Tatkal).",
        examples=["GN"],
    ),
]
EligibilityState = Literal[
    "NOT_APPLICABLE",
    "NOT_YET_OPEN",
    "OPENS_TODAY",
    "OPEN",
    "OPENING_PASSED",
    "JOURNEY_DATE_PASSED",
    "CLASS_CATEGORY_UNKNOWN",
    "UNDETERMINED",
    "PROVIDER_UNSUPPORTED",
]


class QuotaEligibilityOut(ApiModel):
    """Whether RailRoute may query a quota now. Says nothing about availability."""

    quota: QuotaLiteral
    state: EligibilityState
    queryable: bool = Field(description="True when the provider may be asked for this quota.")
    class_category: Literal["AC", "NON_AC"] | None = Field(
        description="Category that sets the opening time; null when the class is unclassified."
    )
    train_origin_date: date | None = Field(
        description="Date the train leaves its origin station: the booking window's anchor."
    )
    opens_at: datetime | None = Field(description="Booking window opening (Asia/Kolkata).")
    message: str

    @classmethod
    def of(cls, eligibility: QuotaEligibility) -> QuotaEligibilityOut:
        return cls(
            quota=eligibility.quota.value,
            state=eligibility.state.value,
            queryable=eligibility.queryable,
            class_category=(
                eligibility.class_category.value if eligibility.class_category else None
            ),
            train_origin_date=eligibility.train_origin_date,
            opens_at=eligibility.opens_at,
            message=describe_eligibility(eligibility),
        )


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
