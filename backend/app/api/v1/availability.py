"""POST /api/v1/availability/check (doc 05 §4): one segment, one class, one quota."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from app.api.deps import ContainerDep, railway_services_open, search_rate_limit
from app.core.errors import SemanticValidationError, require
from app.domain import disclaimers
from app.domain.enums import Quota
from app.domain.models import SegmentKey
from app.domain.quota_eligibility import QuotaEligibility, describe_eligibility
from app.domain.route import provider_query_date, train_start_date, validate_journey
from app.schemas.availability import AvailabilityCheckRequest, AvailabilityCheckResponse
from app.schemas.common import ERROR_RESPONSES
from app.schemas.shared import AvailabilityOut, FareOut, PredictionOut, QuotaEligibilityOut
from app.services.availability import SegmentRequest, run_record
from app.services.journey_search import validate_trip

router = APIRouter(tags=["availability"])


def _not_queried(
    body: AvailabilityCheckRequest,
    container: ContainerDep,
    eligibility: QuotaEligibility,
    *,
    query_date: date,
    start: date | None,
) -> AvailabilityCheckResponse:
    """The provider was deliberately not asked: no availability, never 'unavailable'."""
    warnings = [describe_eligibility(eligibility)]
    if not container.provider.is_live:
        warnings.insert(0, disclaimers.DEMO_MODE)
    quota = eligibility.quota
    return AvailabilityCheckResponse(
        train_number=body.train_number,
        source=body.source,
        destination=body.destination,
        journey_date=body.journey_date,
        provider_query_date=query_date,
        train_start_date=start,
        travel_class=body.travel_class,
        quota=quota.value,
        quota_label=quota.label,
        queried=False,
        eligibility=QuotaEligibilityOut.of(eligibility),
        availability=None,
        prediction=None,
        fare=None,
        provider=container.provider.name,
        provider_checked_at=None,
        checked_at=None,
        cached=False,
        anomalies=[],
        data_mode=container.data_mode,  # type: ignore[arg-type]
        warnings=warnings,
    )


@router.post(
    "/availability/check",
    response_model=AvailabilityCheckResponse,
    responses=ERROR_RESPONSES,
    dependencies=[railway_services_open, search_rate_limit],
    summary="Check one segment on one train (single ticket, one quota)",
)
async def check_availability(
    body: AvailabilityCheckRequest, container: ContainerDep
) -> AvailabilityCheckResponse:
    settings = container.settings
    quota = Quota(body.quota or Quota.GENERAL.value)
    validate_trip(
        settings,
        container.clock,
        body.source,
        body.destination,
        body.journey_date,
        [body.travel_class],
    )
    if not container.eligibility.is_supported(quota):  # decided before any provider call
        unsupported = container.eligibility.evaluate(
            quota, body.travel_class, train_origin_date=None, boarding_date=body.journey_date
        )
        return _not_queried(body, container, unsupported, query_date=body.journey_date, start=None)

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
    # The booking window depends on the train's origin date, never on the boarding date.
    eligibility = container.eligibility.evaluate(
        quota, body.travel_class, train_origin_date=start, boarding_date=body.journey_date
    )
    if not eligibility.queryable:
        return _not_queried(body, container, eligibility, query_date=query_date, start=start)

    request = SegmentRequest(
        SegmentKey(
            body.train_number, start, body.source, body.destination, body.travel_class, quota
        ),
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
        quota=quota.value,
        quota_label=quota.label,
        queried=True,
        eligibility=QuotaEligibilityOut.of(eligibility),
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
