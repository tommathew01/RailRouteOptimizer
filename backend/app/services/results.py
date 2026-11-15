"""Assemble the public result (and its persisted snapshot) from search state.

Everything user-facing about a recommendation is decided here: segment times in IST, provider
attribution, the non-probabilistic prediction summary, fare completeness, booking steps and
warnings. Nothing is invented: absent provider fields stay null.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.core.errors import require
from app.domain import disclaimers
from app.domain.enums import (
    AvailabilityStatus,
    IncompleteReason,
    SearchCompleteness,
    StatusTier,
    TravelClass,
)
from app.domain.route import boards_on_other_calendar_day, scheduled_arrival, scheduled_departure
from app.optimization.planner import ComboProgress
from app.optimization.ranking import RankedPath
from app.repositories.records import (
    RecommendationRecord,
    RecommendationSegmentRecord,
    SearchRecord,
)
from app.schemas.journeys import (
    ClassEvaluation,
    Coverage,
    JourneyFilters,
    JourneySearchResponse,
    PredictionSummary,
    RecommendationOut,
    SearchError,
    SearchRequestEcho,
    SegmentOut,
    TrainEvaluation,
)
from app.schemas.shared import FareOut, PredictionOut
from app.services.search_state import ComboContext, SearchContext, TrainContext

TIER_LABELS = {
    StatusTier.ALL_CONFIRMED_OR_AVAILABLE: "All segments confirmed or available",
    StatusTier.INCLUDES_RAC: "Includes RAC",
    StatusTier.INCLUDES_WAITLIST: "Includes waitlist",
}

INCOMPLETE_MESSAGES = {
    IncompleteReason.AVAILABILITY_REQUEST_BUDGET_REACHED: (
        "The per-search availability request budget was used up before every candidate segment "
        "could be checked."
    ),
    IncompleteReason.PROVIDER_QUOTA_GUARD_REACHED: (
        "The provider request quota guard stopped further checks (plan limit or safety guard)."
    ),
    IncompleteReason.PROVIDER_RATE_LIMITED: "The provider rate-limited requests; checks stopped.",
    IncompleteReason.PROVIDER_AUTH_ERROR: "The provider rejected our credentials; checks stopped.",
    IncompleteReason.PROVIDER_ERRORS: "Some provider checks failed or returned unclear answers.",
    IncompleteReason.SEARCH_DEADLINE_REACHED: "The search reached its time limit.",
}


def status_url(search_id: uuid.UUID) -> str:
    return f"/api/v1/journeys/{search_id}"


def class_label(code: str) -> str:
    try:
        return TravelClass(code).label
    except ValueError:
        return code


def _fmt(moment: datetime | None) -> str:
    return "time unavailable" if moment is None else moment.strftime("%d %b %Y %H:%M")


def completeness(
    ctx: SearchContext, *, has_recommendations: bool
) -> tuple[SearchCompleteness, IncompleteReason | None]:
    stats = ctx.stats
    reason: IncompleteReason | None
    if stats.deadline_hit:
        state, reason = SearchCompleteness.PARTIAL_TIMEOUT, IncompleteReason.SEARCH_DEADLINE_REACHED
    elif stats.stop_reason in (
        IncompleteReason.AVAILABILITY_REQUEST_BUDGET_REACHED,
        IncompleteReason.PROVIDER_QUOTA_GUARD_REACHED,
    ):
        state, reason = SearchCompleteness.PARTIAL_BUDGET, stats.stop_reason
    elif stats.stop_reason is not None:
        state, reason = SearchCompleteness.PARTIAL_PROVIDER_ERRORS, stats.stop_reason
    elif stats.segments_failed or stats.segments_unknown or stats.route_failures:
        state, reason = SearchCompleteness.PARTIAL_PROVIDER_ERRORS, IncompleteReason.PROVIDER_ERRORS
    else:
        state, reason = SearchCompleteness.COMPLETE, None
    if not has_recommendations:
        if state is SearchCompleteness.COMPLETE:
            return SearchCompleteness.NO_PATH_FOUND, None
        return SearchCompleteness.NO_PATH_FOUND_PARTIAL, reason
    return state, reason


def _segment_outs(ranked: RankedPath, combo: ComboContext) -> list[SegmentOut]:
    train = combo.train
    analysis = require(train.analysis, "route analysis")
    start = require(train.start_date, "train start date")
    source_index = require(require(train.journey, "journey").source_index, "source index")
    stops = analysis.route.stops
    outs = []
    for sequence, edge in enumerate(ranked.path.edges):
        observation = edge.observation
        record = observation.record
        outs.append(
            SegmentOut(
                sequence=sequence,
                source=edge.from_station,
                source_name=stops[edge.from_index].station_name,
                destination=edge.to_station,
                destination_name=stops[edge.to_index].station_name,
                departure=scheduled_departure(start, analysis, edge.from_index),
                arrival=scheduled_arrival(start, analysis, edge.to_index),
                provider_query_date=observation.provider_date,
                boards_on_later_date=boards_on_other_calendar_day(
                    analysis, source_index, edge.from_index
                ),
                status=record.status.value,
                availability_text=record.availability_text,
                raw_status=record.raw_status,
                waitlist_type=record.waitlist_type,
                waitlist_number=record.waitlist_number,
                rac_number=record.rac_number,
                available_count=record.available_count,
                can_book=record.can_book,
                prediction=PredictionOut.of(record.prediction),
                fare=FareOut.of(record.fare),
                checked_at=observation.observed_at,
                cached=observation.id in combo.cached_observation_ids,
                observation_id=observation.id,
            )
        )
    return outs


def _booking_steps(ranked: RankedPath, segments: list[SegmentOut]) -> list[str]:
    count = len(segments)
    steps = [
        f"Ticket {s.sequence + 1} of {count}: train {ranked.key.train_number}, "
        f"{s.source} → {s.destination}, departing {_fmt(s.departure)} IST, class "
        f"{ranked.key.travel_class}, General (GN) quota."
        for s in segments
    ]
    if count > 1:
        changes = ", ".join(s.source for s in segments[1:])
        steps.append(
            f"Book each ticket separately; each may get its own PNR, coach and berth. "
            f"You may need to change seats at {changes}."
        )
    steps.append("Check every ticket on an authorized booking platform before paying.")
    return steps


def recommendation_outs(
    ctx: SearchContext, ranked: list[tuple[RankedPath, ComboContext]]
) -> list[RecommendationOut]:
    outs = []
    for item, combo in ranked:
        segments = _segment_outs(item, combo)
        fare = item.fare
        outs.append(
            RecommendationOut(
                rank=item.rank,
                train_number=item.key.train_number,
                train_name=combo.train.name,
                travel_class=item.key.travel_class,
                travel_class_label=class_label(item.key.travel_class),
                train_start_date=item.key.train_start_date,
                segment_count=item.path.segment_count,
                status_tier=int(item.status_tier),
                status_tier_label=TIER_LABELS[item.status_tier],
                segments=segments,
                total_fare=(
                    FareOut(amount=fare.total, currency=fare.currency)
                    if fare.complete and fare.total is not None and fare.currency
                    else None
                ),
                fare_complete=fare.complete,
                prediction_summary=PredictionSummary(
                    minimum_percentage=item.prediction_floor,
                    segments_with_estimate=item.predictions_present,
                    segments_needing_estimate=item.predictions_needed,
                ),
                explanation=list(item.explanation),
                booking_steps=_booking_steps(item, segments),
                oldest_checked_at=item.oldest_observed_at,
            )
        )
    return outs


def _class_evaluations(
    train: TrainContext,
    ctx: SearchContext,
    progress: dict[int, ComboProgress],
    counts: dict[int, int],
) -> list[ClassEvaluation]:
    evaluations = []
    for travel_class in ctx.request.classes:
        combo = next(
            (c for c in ctx.combos.values() if c.train is train and c.travel_class == travel_class),
            None,
        )
        if combo is None:
            evaluations.append(
                ClassEvaluation(
                    travel_class=travel_class,
                    state=train.class_states.get(travel_class, "NOT_EVALUATED"),  # type: ignore[arg-type]
                    depth_reached=0,
                    best_status_tier=None,
                    recommendations=0,
                )
            )
            continue
        info = progress.get(combo.combo_id)
        evaluations.append(
            ClassEvaluation(
                travel_class=travel_class,
                state=info.state.value if info else "NOT_EVALUATED",
                depth_reached=info.depth_reached if info else 0,
                best_status_tier=(
                    int(info.best_complete_tier)
                    if info and info.best_complete_tier is not None
                    else None
                ),
                recommendations=counts.get(combo.combo_id, 0),
            )
        )
    return evaluations


def train_evaluations(ctx: SearchContext, counts: dict[int, int]) -> list[TrainEvaluation]:
    progress = {p.combo_id: p for p in ctx.planner.progress()} if ctx.planner else {}
    out = []
    for train in ctx.trains:
        departure = arrival = None
        journey = train.journey
        if train.analysis and train.start_date and journey and journey.verified:
            source = require(journey.source_index, "source index")
            destination = require(journey.destination_index, "destination index")
            departure = scheduled_departure(train.start_date, train.analysis, source)
            arrival = scheduled_arrival(train.start_date, train.analysis, destination)
        out.append(
            TrainEvaluation(
                train_number=train.train_number,
                train_name=train.name,
                evaluation=train.evaluation,  # type: ignore[arg-type]
                route_issues=train.issues,
                departure=departure,
                arrival=arrival,
                intermediate_stops_total=journey.total_intermediate_stops if journey else 0,
                intermediate_stops_considered=len(train.considered),
                classes=_class_evaluations(train, ctx, progress, counts),
            )
        )
    return out


def coverage(ctx: SearchContext) -> Coverage:
    planner = ctx.planner
    outstanding = planner.outstanding_edges() if planner else 0
    made = ctx.budget.used
    return Coverage(
        trains_found=ctx.stats.trains_found,
        trains_evaluated=sum(1 for t in ctx.trains if t.evaluation == "EVALUATED"),
        combinations_evaluated=len(ctx.combos),
        availability_requests_planned=made + ctx.stats.cache_hits + outstanding,
        availability_requests_made=made,
        request_budget=ctx.budget.limit,
        cache_hits=ctx.stats.cache_hits,
        segments_checked=ctx.stats.segments_checked,
        segments_unknown=ctx.stats.segments_unknown,
        segments_failed=ctx.stats.segments_failed,
    )


def warnings_for(
    ctx: SearchContext,
    recommendations: list[RecommendationOut],
    state: SearchCompleteness | None,
    reason: IncompleteReason | None,
    *,
    demo: bool,
    date_policy_verified: bool,
) -> list[str]:
    notes: list[str] = []
    if demo:
        notes.append(disclaimers.DEMO_MODE)
    notes.extend(ctx.request.notes)
    notes.extend(ctx.warnings)
    if reason is not None:
        notes.append(INCOMPLETE_MESSAGES[reason])
    if state is SearchCompleteness.NO_PATH_FOUND_PARTIAL:
        notes.append("No combination found in the segments checked. That does not mean none exist.")
    elif state is SearchCompleteness.NO_PATH_FOUND and ctx.stats.trains_found:
        notes.append("No combination of up to the allowed tickets is available with these filters.")
    if not date_policy_verified and any(
        seg.boards_on_later_date for rec in recommendations for seg in rec.segments
    ):
        notes.append(disclaimers.DATE_POLICY_UNVERIFIED)
    notes.extend(disclaimers.ALWAYS)
    return list(dict.fromkeys(notes))


def build_response(
    record: SearchRecord,
    ctx: SearchContext | None,
    *,
    recommendations: list[RecommendationOut],
    counts: dict[int, int],
    data_mode: str,
    stale_after_seconds: int,
    date_policy_verified: bool,
    error: SearchError | None = None,
) -> JourneySearchResponse:
    request = SearchRequestEcho(
        source=record.source,
        destination=record.destination,
        journey_date=record.journey_date,
        classes=record.classes,
        filters=JourneyFilters(**record.filters),
        max_segments=record.max_segments,
        train_numbers=record.train_numbers,
    )
    warnings = (
        warnings_for(
            ctx,
            recommendations,
            record.search_completeness,
            record.incomplete_reason,
            demo=data_mode == "DEMO",
            date_policy_verified=date_policy_verified,
        )
        if ctx
        else ([disclaimers.DEMO_MODE] if data_mode == "DEMO" else []) + list(disclaimers.ALWAYS)
    )
    return JourneySearchResponse(
        search_id=record.id,
        status=record.status.value,
        status_url=status_url(record.id),
        data_mode=data_mode,  # type: ignore[arg-type]
        provider=record.provider,
        request=request,
        search_completeness=record.search_completeness.value
        if record.search_completeness
        else None,
        incomplete_reason=record.incomplete_reason.value if record.incomplete_reason else None,
        coverage=coverage(ctx) if ctx else None,
        trains=train_evaluations(ctx, counts) if ctx else [],
        recommendations=recommendations,
        warnings=warnings,
        error=error,
        stale_after_seconds=stale_after_seconds,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def recommendation_records(
    search_id: uuid.UUID,
    ranked: list[tuple[RankedPath, ComboContext]],
    *,
    created_at: datetime,
) -> list[RecommendationRecord]:
    records = []
    for item, combo in ranked:
        records.append(
            RecommendationRecord(
                id=uuid.uuid4(),
                search_id=search_id,
                rank=item.rank,
                train_number=item.key.train_number,
                train_name=combo.train.name,
                travel_class=item.key.travel_class,
                quota=item.key.quota.value,
                train_start_date=item.key.train_start_date,
                segment_count=item.path.segment_count,
                status_tier=int(item.status_tier),
                fare_complete=item.fare.complete,
                created_at=created_at,
                segments=tuple(
                    RecommendationSegmentRecord(i, e.from_station, e.to_station, e.observation.id)
                    for i, e in enumerate(item.path.edges)
                ),
                ranking_metadata={
                    "prediction_floor": item.prediction_floor,
                    "predictions_present": item.predictions_present,
                    "predictions_needed": item.predictions_needed,
                    "statuses": [e.observation.record.status.value for e in item.path.edges],
                    "explanation": list(item.explanation),
                },
                total_fare=item.fare.total,
                currency=item.fare.currency,
            )
        )
    return records


def uncertain_prediction_coverage(recommendations: list[RecommendationOut]) -> float | None:
    needed = present = 0
    for rec in recommendations:
        for seg in rec.segments:
            if seg.status in (AvailabilityStatus.RAC.value, AvailabilityStatus.WAITLIST.value):
                needed += 1
                present += int(seg.prediction is not None and seg.prediction.percentage is not None)
    return None if needed == 0 else present / needed
