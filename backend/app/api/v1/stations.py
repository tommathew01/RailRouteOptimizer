"""GET /api/v1/stations/search (doc 05 §1)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep, lookup_rate_limit
from app.schemas.catalog import StationOut, StationSearchResponse
from app.schemas.common import ERROR_RESPONSES

router = APIRouter(tags=["stations"])


@router.get(
    "/stations/search",
    response_model=StationSearchResponse,
    responses=ERROR_RESPONSES,
    dependencies=[lookup_rate_limit],
    summary="Search stations by name or code",
)
async def search_stations(
    container: ContainerDep,
    q: Annotated[str, Query(min_length=1, max_length=50, description="Station name or code")],
) -> StationSearchResponse:
    stations = await container.stations.search(q)
    return StationSearchResponse(
        items=[StationOut.of(s) for s in stations],
        data_mode=container.data_mode,  # type: ignore[arg-type]
    )
