"""Public, non-secret configuration for clients."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.domain import disclaimers
from app.domain.enums import TravelClass
from app.schemas.meta import ClassOption, MetaResponse, QuotaInfo, SearchLimits

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=MetaResponse, summary="Client configuration and disclaimers")
async def meta(container: ContainerDep) -> MetaResponse:
    settings = container.settings
    notes = list(disclaimers.ALWAYS)
    if settings.is_demo_mode:
        notes.insert(0, disclaimers.DEMO_MODE)
    return MetaResponse(
        app_name=settings.app_name,
        data_mode="DEMO" if settings.is_demo_mode else "LIVE",
        provider=settings.railway_provider.value.upper(),
        quota=QuotaInfo(),
        supported_classes=[
            ClassOption(code=code, label=TravelClass(code).label)
            for code in settings.supported_classes
        ],
        limits=SearchLimits(
            max_segments=settings.max_segments,
            max_trains_per_search=settings.search_max_trains,
            max_availability_requests_per_search=settings.search_max_availability_requests,
            max_advance_booking_days=settings.max_advance_booking_days,
        ),
        station_search_min_query_length=settings.station_search_min_query_length,
        stale_after_seconds=settings.stale_after_seconds,
        availability_date_policy=settings.availability_date_policy.value,
        availability_date_policy_verified=settings.availability_date_policy_verified,
        disclaimers=notes,
    )
