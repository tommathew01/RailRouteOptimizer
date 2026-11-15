"""Public configuration the client needs to render honest UI (demo mode, limits, disclaimers)."""

from __future__ import annotations

from typing import Literal

from app.schemas.common import ApiModel


class ClassOption(ApiModel):
    code: str
    label: str


class QuotaInfo(ApiModel):
    code: Literal["GN"] = "GN"
    label: str = "General"
    editable: bool = False


class SearchLimits(ApiModel):
    max_segments: int
    max_trains_per_search: int
    max_availability_requests_per_search: int
    max_advance_booking_days: int


class MetaResponse(ApiModel):
    app_name: str
    api_version: Literal["v1"] = "v1"
    data_mode: Literal["DEMO", "LIVE"]
    provider: str
    quota: QuotaInfo
    supported_classes: list[ClassOption]
    limits: SearchLimits
    station_search_min_query_length: int
    stale_after_seconds: int
    availability_date_policy: str
    availability_date_policy_verified: bool
    disclaimers: list[str]
