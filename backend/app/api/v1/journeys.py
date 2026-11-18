"""POST /api/v1/journeys/optimize and GET /api/v1/journeys/{search_id} (doc 05 §5-6)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import ContainerDep, lookup_rate_limit, railway_services_open, search_rate_limit
from app.core.errors import NotFoundError
from app.domain.enums import SearchStatus
from app.schemas.common import ERROR_RESPONSES
from app.schemas.journeys import (
    JourneySearchResponse,
    OptimizeRequest,
    SearchAccepted,
    SearchPlanResponse,
    SearchStopResponse,
)
from app.services.journey_search import JourneySearchService
from app.services.results import plan_response, status_url
from app.services.search_state import JourneyRequest

router = APIRouter(tags=["journeys"])


def _prepare(body: OptimizeRequest, container: ContainerDep) -> JourneyRequest:
    return container.journeys.prepare(
        source=body.source,
        destination=body.destination,
        journey_date=body.journey_date,
        classes=body.classes,
        allow_rac=body.filters.allow_rac,
        allow_waitlist=body.filters.allow_waitlist,
        max_segments=body.max_segments,
        train_numbers=body.train_numbers,
        client_quota=body.quota,
        quotas=list(body.quotas),
    )


@router.post(
    "/journeys/preview",
    response_model=SearchPlanResponse,
    responses=ERROR_RESPONSES,
    dependencies=[railway_services_open, lookup_rate_limit],
    summary="Combinations a search would check now and how the budget would be shared",
)
async def preview(body: OptimizeRequest, container: ContainerDep) -> SearchPlanResponse:
    """Same validation as ``/journeys/optimize``; never makes an availability request."""
    ctx = await container.journeys.preview(_prepare(body, container))
    return plan_response(
        ctx,
        data_mode=container.data_mode,
        provider_quotas=container.eligibility.supported_quotas,
    )


@router.post(
    "/journeys/optimize",
    status_code=202,
    responses={
        **ERROR_RESPONSES,
        200: {"model": JourneySearchResponse, "description": "Completed (synchronous mode)"},
        202: {"model": SearchAccepted, "description": "Accepted; poll status_url"},
    },
    dependencies=[railway_services_open, search_rate_limit],
    summary="Find same-train segment combinations (1-4 separate tickets)",
)
async def optimize(body: OptimizeRequest, container: ContainerDep) -> JSONResponse:
    record = await container.journeys.submit(_prepare(body, container))
    if record.status in (SearchStatus.COMPLETED, SearchStatus.FAILED):
        response = JourneySearchService.response_for(record)
        return JSONResponse(response.model_dump(mode="json"), status_code=200)
    accepted = SearchAccepted(
        search_id=record.id,
        status=record.status.value,  # type: ignore[arg-type]
        status_url=status_url(record.id),
    )
    return JSONResponse(
        accepted.model_dump(mode="json"),
        status_code=202,
        headers={"Location": accepted.status_url},
    )


@router.get(
    "/journeys/{search_id}",
    response_model=JourneySearchResponse,
    responses=ERROR_RESPONSES,
    dependencies=[lookup_rate_limit],
    summary="Search state, progress and (partial) results",
)
async def get_search(search_id: uuid.UUID, container: ContainerDep) -> JourneySearchResponse:
    record = await container.journeys.get(search_id)
    if record is None:
        raise NotFoundError("Search not found.", code="SEARCH_NOT_FOUND")
    return JourneySearchService.response_for(record)


@router.post(
    "/journeys/{search_id}/stop",
    response_model=SearchStopResponse,
    status_code=202,
    responses={
        **ERROR_RESPONSES,
        200: {"model": SearchStopResponse, "description": "Already finished: nothing to stop"},
        202: {"model": SearchStopResponse, "description": "Stop requested; poll status_url"},
    },
    dependencies=[lookup_rate_limit],
    summary="Stop a running search and keep the results checked so far",
)
async def stop_search(search_id: uuid.UUID, container: ContainerDep) -> JSONResponse:
    """No new availability request is sent after this; requests already sent finish and are
    kept. Idempotent: repeated calls change nothing. Never starts another search."""
    outcome = await container.journeys.request_stop(search_id)
    if outcome is None:
        raise NotFoundError("Search not found.", code="SEARCH_NOT_FOUND")
    record, requested = outcome
    body = SearchStopResponse(
        search_id=record.id,
        status=record.status.value,
        stop_requested=requested,
        status_url=status_url(record.id),
        message=(
            "Stopping: no new availability checks will be sent; results so far are kept."
            if requested
            else "The search had already finished; nothing was stopped."
        ),
    )
    return JSONResponse(body.model_dump(mode="json"), status_code=202 if requested else 200)
