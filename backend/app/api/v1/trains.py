"""POST /api/v1/trains/search and GET /api/v1/trains/{train_number}/route (doc 05 §2-3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import ContainerDep, lookup_rate_limit
from app.core.errors import NotFoundError
from app.providers.errors import ProviderError, ProviderErrorCategory
from app.schemas.catalog import (
    TrainOut,
    TrainRouteResponse,
    TrainSearchRequest,
    TrainSearchResponse,
)
from app.schemas.common import ERROR_RESPONSES
from app.services.journey_search import validate_trip

router = APIRouter(tags=["trains"])


@router.post(
    "/trains/search",
    response_model=TrainSearchResponse,
    responses=ERROR_RESPONSES,
    dependencies=[lookup_rate_limit],
    summary="Find trains between two stations on a date",
)
async def search_trains(body: TrainSearchRequest, container: ContainerDep) -> TrainSearchResponse:
    validate_trip(
        container.settings, container.clock, body.source, body.destination, body.journey_date, []
    )
    trains = await container.trains.search_trains(body.source, body.destination, body.journey_date)
    return TrainSearchResponse(
        source=body.source,
        destination=body.destination,
        journey_date=body.journey_date,
        trains=[TrainOut.of(t, body.source, body.destination) for t in trains],
        data_mode=container.data_mode,  # type: ignore[arg-type]
        provider=container.provider.name,
    )


@router.get(
    "/trains/{train_number}/route",
    response_model=TrainRouteResponse,
    responses=ERROR_RESPONSES,
    dependencies=[lookup_rate_limit],
    summary="Ordered route of a train with validation result",
)
async def train_route(
    container: ContainerDep,
    train_number: Annotated[str, Path(pattern=r"^\d{5}$", description="Five-digit train number")],
) -> TrainRouteResponse:
    try:
        route, analysis = await container.trains.get_route(train_number)
    except ProviderError as error:
        if error.category is ProviderErrorCategory.NOT_FOUND:
            raise NotFoundError("Train not found.", code="TRAIN_NOT_FOUND") from error
        raise
    return TrainRouteResponse.of(
        route,
        verified=analysis.verified,
        issues=[issue.value for issue in analysis.issues],
        data_mode=container.data_mode,  # type: ignore[arg-type]
    )
