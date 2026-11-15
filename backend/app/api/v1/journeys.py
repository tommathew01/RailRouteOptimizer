"""POST /api/v1/journeys/optimize and GET /api/v1/journeys/{search_id} (doc 05 §5-6)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import ContainerDep, lookup_rate_limit, search_rate_limit
from app.core.errors import NotFoundError
from app.domain.enums import SearchStatus
from app.schemas.common import ERROR_RESPONSES
from app.schemas.journeys import JourneySearchResponse, OptimizeRequest, SearchAccepted
from app.services.journey_search import JourneySearchService
from app.services.results import status_url

router = APIRouter(tags=["journeys"])


@router.post(
    "/journeys/optimize",
    status_code=202,
    responses={
        **ERROR_RESPONSES,
        200: {"model": JourneySearchResponse, "description": "Completed (synchronous mode)"},
        202: {"model": SearchAccepted, "description": "Accepted; poll status_url"},
    },
    dependencies=[search_rate_limit],
    summary="Find same-train segment combinations (1-4 separate tickets)",
)
async def optimize(body: OptimizeRequest, container: ContainerDep) -> JSONResponse:
    request = container.journeys.prepare(
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
    record = await container.journeys.submit(request)
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
