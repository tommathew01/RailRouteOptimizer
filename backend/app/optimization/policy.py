"""Hard eligibility rules and status tiers (doc 04 §3, §5). Unknown is never usable."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.enums import AvailabilityStatus, StatusTier

#: Binding product decision: at most four separate tickets per recommendation.
MAX_SEGMENTS = 4


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Doc 04 default: only CONFIRMED/AVAILABLE unless RAC / waitlist are explicitly allowed."""

    allow_rac: bool = False
    allow_waitlist: bool = False


class EdgeEligibility(StrEnum):
    USABLE = "USABLE"
    EXCLUDED_RAC = "EXCLUDED_RAC"
    EXCLUDED_WAITLIST = "EXCLUDED_WAITLIST"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    UNKNOWN = "UNKNOWN"


_TIER = {
    AvailabilityStatus.CONFIRMED: StatusTier.ALL_CONFIRMED_OR_AVAILABLE,
    AvailabilityStatus.AVAILABLE: StatusTier.ALL_CONFIRMED_OR_AVAILABLE,
    AvailabilityStatus.RAC: StatusTier.INCLUDES_RAC,
    AvailabilityStatus.WAITLIST: StatusTier.INCLUDES_WAITLIST,
}


def status_tier(status: AvailabilityStatus) -> StatusTier | None:
    return _TIER.get(status)


def classify(status: AvailabilityStatus, filters: SearchFilters) -> EdgeEligibility:
    if status in (AvailabilityStatus.CONFIRMED, AvailabilityStatus.AVAILABLE):
        return EdgeEligibility.USABLE
    if status is AvailabilityStatus.RAC:
        return EdgeEligibility.USABLE if filters.allow_rac else EdgeEligibility.EXCLUDED_RAC
    if status is AvailabilityStatus.WAITLIST:
        return (
            EdgeEligibility.USABLE if filters.allow_waitlist else EdgeEligibility.EXCLUDED_WAITLIST
        )
    if status is AvailabilityStatus.NOT_AVAILABLE:
        return EdgeEligibility.NOT_AVAILABLE
    return EdgeEligibility.UNKNOWN
