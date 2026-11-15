"""Public configuration the client needs to render honest UI (demo mode, limits, disclaimers)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.shared import QuotaLiteral


class ClassOption(ApiModel):
    code: str
    label: str
    category: Literal["AC", "NON_AC"] | None = Field(
        default=None, description="Sets the Tatkal opening time; null when unclassified."
    )


class QuotaInfo(ApiModel):
    """Deprecated: the default quota. See ``MetaResponse.quotas`` for the selectable ones."""

    code: Literal["GN"] = "GN"
    label: str = "General"
    editable: bool = True


class OpeningRuleOut(ApiModel):
    reference: Literal["TRAIN_ORIGIN_DATE"] = Field(
        default="TRAIN_ORIGIN_DATE",
        description="The window is anchored to the date the train leaves its origin station.",
    )
    days_before: int
    ac_opens_at: str = Field(description="IST wall-clock time, HH:MM.")
    non_ac_opens_at: str = Field(description="IST wall-clock time, HH:MM.")
    timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"


class QuotaOption(ApiModel):
    code: QuotaLiteral
    label: str
    default: bool
    provider_supported: bool
    opening_rule: OpeningRuleOut | None = Field(
        description="Null when no booking window applies (General)."
    )
    note: str | None = None


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
    quotas: list[QuotaOption]
    supported_classes: list[ClassOption]
    limits: SearchLimits
    station_search_min_query_length: int
    stale_after_seconds: int
    availability_date_policy: str
    availability_date_policy_verified: bool
    disclaimers: list[str]
