"""Public, non-secret configuration for clients."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.domain import disclaimers
from app.domain.enums import QUOTA_ORDER, Quota, TravelClass
from app.domain.maintenance import MaintenanceWindow
from app.domain.quota_eligibility import class_category
from app.schemas.meta import (
    ClassOption,
    MaintenanceWindowOut,
    MetaResponse,
    OpeningRuleOut,
    QuotaInfo,
    QuotaOption,
    SearchLimits,
)

router = APIRouter(tags=["meta"])


def _quota_options(container: ContainerDep) -> list[QuotaOption]:
    options = []
    for quota in QUOTA_ORDER:
        rule = container.eligibility.rule(quota)
        supported = container.eligibility.is_supported(quota)
        options.append(
            QuotaOption(
                code=quota.value,
                label=quota.label,
                default=quota is Quota.GENERAL,
                provider_supported=supported,
                opening_rule=(
                    OpeningRuleOut(
                        days_before=rule.days_before,
                        ac_opens_at=rule.ac_opens_at.strftime("%H:%M"),
                        non_ac_opens_at=rule.non_ac_opens_at.strftime("%H:%M"),
                    )
                    if rule
                    else None
                ),
                note=None if supported else "Not supported by the railway data provider.",
            )
        )
    return options


def _maintenance(container: ContainerDep) -> MaintenanceWindowOut:
    settings = container.settings
    window = MaintenanceWindow(settings.railway_maintenance_start, settings.railway_maintenance_end)
    return MaintenanceWindowOut(
        enabled=settings.railway_maintenance_enabled,
        starts_at=window.starts.strftime("%H:%M"),
        ends_at=window.ends.strftime("%H:%M"),
        message=window.describe(),
    )


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
        quotas=_quota_options(container),
        supported_classes=[
            ClassOption(
                code=code,
                label=TravelClass(code).label,
                category=category.value if (category := class_category(code)) else None,
            )
            for code in settings.supported_classes
        ],
        limits=SearchLimits(
            max_segments=settings.max_segments,
            max_trains_per_search=settings.search_max_trains,
            max_classes_per_search=settings.max_classes_per_search,
            max_availability_requests_per_search=settings.search_max_availability_requests,
            max_advance_booking_days=settings.max_advance_booking_days,
        ),
        railway_maintenance=_maintenance(container),
        station_search_min_query_length=settings.station_search_min_query_length,
        stale_after_seconds=settings.stale_after_seconds,
        availability_date_policy=settings.availability_date_policy.value,
        availability_date_policy_verified=settings.availability_date_policy_verified,
        disclaimers=notes,
    )
