"""Builders for optimization tests (domain objects only)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from app.domain.enums import AvailabilityStatus, Quota
from app.domain.models import AvailabilityRecord, Fare, Prediction, SegmentKey, SegmentObservation
from app.optimization.graph import GraphKey

START = date(2026, 11, 20)
OBSERVED = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)
ROUTE = ("TIR", "SRR", "TCR", "AWY", "ERS", "KTYM", "QLN", "TVC")  # docs/04 §9 worked example
INDEX = {code: i for i, code in enumerate(ROUTE)}

S = AvailabilityStatus


def key(train: str = "12345", cls: str = "3A", start: date = START) -> GraphKey:
    return GraphKey(train, start, cls)


def obs(
    src: str,
    dst: str,
    status: AvailabilityStatus,
    *,
    train: str = "12345",
    cls: str = "3A",
    start: date = START,
    quota: Quota = Quota.GENERAL,
    pct: float | None = None,
    fare: str | None = None,
    currency: str = "INR",
    observed_at: datetime = OBSERVED,
) -> SegmentObservation:
    prediction = None if pct is None else Prediction("RAILKIT", f"{pct:g}% Chance", pct)
    record = AvailabilityRecord(
        status=status,
        provider="RAILKIT",
        raw_status=status.value,
        prediction=prediction,
        fare=None if fare is None else Fare(Decimal(fare), currency, "TEST"),
    )
    return SegmentObservation(
        id=uuid.uuid5(
            uuid.NAMESPACE_URL, f"{train}/{cls}/{start}/{src}/{dst}/{status}/{pct}/{fare}"
        ),
        key=SegmentKey(train, start, src, dst, cls, quota),
        provider_date=start,
        record=record,
        observed_at=observed_at,
    )
