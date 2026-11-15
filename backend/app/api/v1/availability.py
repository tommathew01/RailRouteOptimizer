"""POST /api/v1/availability/check (doc 05 §4). Quota is always GN; client quota is ignored."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ContainerDep, search_rate_limit
from app.core.errors import SemanticValidationError, require
from app.domain import disclaimers
from app.domain.enums import Quota
from app.domain.models import SegmentKey
from app.domain.route import provider_query_date, train_start_date, validate_journey
from app.schemas.availability import AvailabilityCheckRequest, AvailabilityCheckResponse
from app.schemas.common import ERROR_RESPONSES
from app.schemas.shared import AvailabilityOut, FareOut, PredictionOut
from app.services.availability import SegmentRequest, run_record
from app.services.journey_search import validate_trip

router = APIRouter(tags=["availability"])


@router.post(
    "/availability/check",
    response_model=AvailabilityCheckResponse,
    responses=ERROR_RESPONSES,
    dependencies=[search_rate_limit],
    summary="Check one segment on one train (single-ticket, General quota)",
)
async def check_availability(
    body: AvailabilityCheckRequest, container: ContainerDep
) -> AvailabilityCheckResponse:
    settings = container.settings
    validate_trip(
        settings,
        container.clock,
        body.source,
        body.destination,
        body.journey_date,
        [body.travel_class],
    )
    route, analysis = await container.trains.get_route(body.train_number)
    journey = validate_journey(analysis, body.source, body.destination)
    if not journey.verified:
        raise SemanticValidationError(
            "This train's verified route does not serve the stations in this order.",
            code="INVALID_SEGMENT",
            details={"issues": [issue.value for issue in journey.issues]},
        )
    if route.classes is not None and body.travel_class not in route.classes:
        raise SemanticValidationError(
            f"Class {body.travel_class} is not listed for this train.", code="CLASS_NOT_OFFERED"
        )
    source_index = require(journey.source_index, "source index")
    start = train_start_date(body.journey_date, analysis, source_index)
    query_date = provider_query_date(
        start, analysis, source_index, settings.availability_date_policy
    )
    request = SegmentRequest(
        SegmentKey(body.train_number, start, body.source, body.destination, body.travel_class),
        query_date,
    )
    result = await container.availability.check(request)
    run = run_record(result, search_id=None, clock=container.clock)
    if run is not None:
        await container.persistence.add_segment_runs([run])
    if result.error is not None:
        raise result.error
    observation = require(result.observation, "observation")
    record = observation.record
    warnings = [disclaimers.SINGLE_PASSENGER, disclaimers.BOOKABLE_NOT_CONFIRMED]
    if record.prediction is not None:
        warnings.append(disclaimers.PREDICTION)
    if body.quota and body.quota.strip().upper() != Quota.GENERAL.value:
        warnings.insert(0, "Only General (GN) quota is supported; the requested quota was ignored.")
    if not container.provider.is_live:
        warnings.insert(0, disclaimers.DEMO_MODE)
    return AvailabilityCheckResponse(
        train_number=body.train_number,
        source=body.source,
        destination=body.destination,
        journey_date=body.journey_date,
        provider_query_date=query_date,
        train_start_date=start,
        travel_class=body.travel_class,
        availability=AvailabilityOut.of(record),
        prediction=PredictionOut.of(record.prediction),
        fare=FareOut.of(record.fare),
        provider=record.provider,
        provider_checked_at=record.provider_checked_at,
        checked_at=observation.observed_at,
        cached=result.cache_hit,
        anomalies=list(record.anomalies),
        data_mode=container.data_mode,  # type: ignore[arg-type]
        warnings=warnings,
    )
