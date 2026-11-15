"""Deterministic, explainable ranking (doc 04 §5; decision D-03).

Sort key, best first:
1. status tier (all confirmed/available → includes RAC → includes waitlist);
2. provider prediction — the *lowest* provider percentage among the RAC/WL segments (a weakest-link
   descriptor, never a probability product). Neutral for all-confirmed paths; paths where any
   RAC/WL segment lacks a percentage sort after those with complete predictions;
3. fewer segments (tickets);
4. lower total fare, only when every segment is priced in the same currency;
5. fresher observations (oldest segment observation, minute buckets);
6. a stable tie-breaker (train, class, stations).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.enums import AvailabilityStatus, StatusTier
from app.optimization.graph import GraphKey
from app.optimization.paths import CandidatePath

_UNCERTAIN = (AvailabilityStatus.RAC, AvailabilityStatus.WAITLIST)
_PROVIDER_LABEL = {"RAILKIT": "RailKit", "MOCK": "Demo provider"}


@dataclass(frozen=True, slots=True)
class FareSummary:
    total: Decimal | None
    currency: str | None
    complete: bool


@dataclass(frozen=True, slots=True)
class RankedPath:
    rank: int
    key: GraphKey
    path: CandidatePath
    status_tier: StatusTier
    prediction_floor: float | None
    predictions_present: int
    predictions_needed: int
    fare: FareSummary
    oldest_observed_at: datetime
    explanation: tuple[str, ...]


def summarize_fare(path: CandidatePath) -> FareSummary:
    fares = [edge.observation.record.fare for edge in path.edges]
    if any(fare is None for fare in fares):
        return FareSummary(None, None, complete=False)
    currencies = {fare.currency for fare in fares if fare is not None}
    if len(currencies) != 1:
        return FareSummary(None, None, complete=False)
    total = sum((fare.amount for fare in fares if fare is not None), Decimal("0"))
    return FareSummary(total, currencies.pop(), complete=True)


def _prediction(path: CandidatePath) -> tuple[float | None, int, int]:
    needed = [e for e in path.edges if e.observation.record.status in _UNCERTAIN]
    values = [
        e.observation.record.prediction.percentage
        for e in needed
        if e.observation.record.prediction is not None
        and e.observation.record.prediction.percentage is not None
    ]
    floor = min(values) if needed and len(values) == len(needed) else None
    return floor, len(values), len(needed)


def _tier(path: CandidatePath) -> StatusTier:
    return max(edge.tier for edge in path.edges)


def _explain(
    path: CandidatePath,
    tier: StatusTier,
    floor: float | None,
    present: int,
    needed: int,
    fare: FareSummary,
) -> tuple[str, ...]:
    statuses = [edge.observation.record.status for edge in path.edges]
    provider = _PROVIDER_LABEL.get(path.edges[0].observation.record.provider, "Provider")
    lines: list[str] = []
    if tier is StatusTier.ALL_CONFIRMED_OR_AVAILABLE:
        lines.append("Every segment is currently confirmed or available.")
    elif tier is StatusTier.INCLUDES_RAC:
        lines.append(f"Includes RAC on {statuses.count(AvailabilityStatus.RAC)} segment(s).")
    else:
        lines.append(
            f"Includes a waitlist on {statuses.count(AvailabilityStatus.WAITLIST)} segment(s)."
        )
    if needed:
        if floor is not None:
            lines.append(f"Lowest {provider} estimate on RAC/waitlist segments: {floor:g}%.")
        else:
            lines.append(
                f"{provider} estimate available for {present} of {needed} RAC/waitlist segment(s)."
            )
    count = path.segment_count
    lines.append("Direct: one ticket." if count == 1 else f"{count} separate tickets.")
    if fare.complete and fare.total is not None:
        lines.append(f"Total fare {fare.currency} {fare.total:,.2f} (every segment priced).")
    else:
        lines.append("Total fare unavailable: not every segment has a comparable fare.")
    return tuple(lines)


def rank_paths(
    candidates: Iterable[tuple[GraphKey, CandidatePath]], *, limit: int | None = None
) -> list[RankedPath]:
    scored: list[tuple[tuple[object, ...], RankedPath]] = []
    for key, path in candidates:
        tier = _tier(path)
        floor, present, needed = _prediction(path)
        fare = summarize_fare(path)
        oldest = min(edge.observation.observed_at for edge in path.edges)
        if tier is StatusTier.ALL_CONFIRMED_OR_AVAILABLE:
            prediction_key: tuple[int, float] = (0, 0.0)
        elif floor is not None:
            prediction_key = (0, -floor)
        else:
            prediction_key = (1, 0.0)
        fare_key = (0, fare.total) if fare.complete and fare.total is not None else (1, Decimal(0))
        sort_key = (
            int(tier),
            prediction_key,
            path.segment_count,
            fare_key,
            -int(oldest.timestamp() // 60),
            (key.train_number, key.travel_class, key.train_start_date.isoformat(), path.stations),
        )
        ranked = RankedPath(
            rank=0,
            key=key,
            path=path,
            status_tier=tier,
            prediction_floor=floor,
            predictions_present=present,
            predictions_needed=needed,
            fare=fare,
            oldest_observed_at=oldest,
            explanation=_explain(path, tier, floor, present, needed, fare),
        )
        scored.append((sort_key, ranked))

    scored.sort(key=lambda item: item[0])
    selected = scored if limit is None else scored[:limit]
    return [
        RankedPath(
            rank=position,
            key=item.key,
            path=item.path,
            status_tier=item.status_tier,
            prediction_floor=item.prediction_floor,
            predictions_present=item.predictions_present,
            predictions_needed=item.predictions_needed,
            fare=item.fare,
            oldest_observed_at=item.oldest_observed_at,
            explanation=item.explanation,
        )
        for position, (_, item) in enumerate(selected, start=1)
    ]
