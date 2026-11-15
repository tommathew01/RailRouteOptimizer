"""Tatkal booking-window eligibility (docs/08 D-20, D-21). Standard library only.

Rules (configurable, see ``Settings``; the defaults are the published Tatkal rules):

* The window is anchored to the train's **originating date** (``SegmentKey.train_start_date``) —
  never to the passenger's boarding date, which is later for stops reached after midnight.
* It opens ``days_before`` calendar days earlier (default 1) at an IST wall-clock time that depends
  on the class category: AC 10:00, non-AC 11:00.
* Classes without a known category are never guessed: ``CLASS_CATEGORY_UNKNOWN``, not queried.

Eligibility only decides whether RailRoute may *ask* the provider. An open window says nothing
about availability, and a quota that was not asked is never reported as unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from types import MappingProxyType

from app.domain.enums import Quota
from app.domain.time import IST, ist_datetime, today_ist


class ClassCategory(StrEnum):
    AC = "AC"
    NON_AC = "NON_AC"


_AC, _NON_AC = ClassCategory.AC, ClassCategory.NON_AC

#: The single source of truth for class categories. Codes absent here are deliberately
#: unclassified: ``VC`` (Vistadome Chair Car — RailKit also lists separate ``VA`` Vistadome AC and
#: ``VS`` Vistadome Non-AC codes), ``CH`` and ``HS`` (high-capacity coaches) are ambiguous.
CLASS_CATEGORIES: Mapping[str, ClassCategory] = MappingProxyType(
    {
        "1A": _AC,
        "2A": _AC,
        "3A": _AC,
        "3E": _AC,
        "CC": _AC,
        "EC": _AC,
        "EA": _AC,
        "VA": _AC,
        "SL": _NON_AC,
        "2S": _NON_AC,
        "FC": _NON_AC,
        "VS": _NON_AC,
    }
)


def class_category(travel_class: str) -> ClassCategory | None:
    return CLASS_CATEGORIES.get(travel_class.strip().upper())


class QuotaEligibilityState(StrEnum):
    #: No booking-window rule applies to this quota (General). Queried as before.
    NOT_APPLICABLE = "NOT_APPLICABLE"
    #: The window opens on a later calendar day (IST).
    NOT_YET_OPEN = "NOT_YET_OPEN"
    #: The window opens later today (IST).
    OPENS_TODAY = "OPENS_TODAY"
    #: The window has opened and the train has not reached its originating date yet.
    OPEN = "OPEN"
    #: The opening day is over (it is the origin date or later); booking may still be possible
    #: until charting, so the provider is asked for the actual status.
    OPENING_PASSED = "OPENING_PASSED"
    #: The passenger's journey (boarding) date is before today (IST).
    JOURNEY_DATE_PASSED = "JOURNEY_DATE_PASSED"
    #: The class has no known AC/non-AC category, so the opening time is unknown.
    CLASS_CATEGORY_UNKNOWN = "CLASS_CATEGORY_UNKNOWN"
    #: The origin date or journey date is missing or inconsistent.
    UNDETERMINED = "UNDETERMINED"
    #: The configured railway data provider does not support this quota.
    PROVIDER_UNSUPPORTED = "PROVIDER_UNSUPPORTED"


QUERYABLE_STATES: frozenset[QuotaEligibilityState] = frozenset(
    {
        QuotaEligibilityState.NOT_APPLICABLE,
        QuotaEligibilityState.OPEN,
        QuotaEligibilityState.OPENING_PASSED,
    }
)


@dataclass(frozen=True, slots=True)
class OpeningRule:
    """When a quota's booking window opens, relative to the train's originating date."""

    days_before: int
    ac_opens_at: time
    non_ac_opens_at: time

    def __post_init__(self) -> None:
        if self.days_before < 0:
            raise ValueError("days_before must not be negative")

    def opening_time(self, category: ClassCategory) -> time:
        return self.ac_opens_at if category is ClassCategory.AC else self.non_ac_opens_at


@dataclass(frozen=True, slots=True)
class QuotaEligibility:
    quota: Quota
    travel_class: str
    state: QuotaEligibilityState
    class_category: ClassCategory | None = None
    train_origin_date: date | None = None
    #: Window opening moment (Asia/Kolkata), when it could be determined.
    opens_at: datetime | None = None

    @property
    def queryable(self) -> bool:
        return self.state in QUERYABLE_STATES

    @property
    def awaiting_opening(self) -> bool:
        return self.state in (QuotaEligibilityState.NOT_YET_OPEN, QuotaEligibilityState.OPENS_TODAY)


def evaluate_quota_eligibility(
    *,
    quota: Quota,
    travel_class: str,
    train_origin_date: date | None,
    boarding_date: date | None,
    now: datetime,
    rule: OpeningRule | None,
    provider_supported: bool,
) -> QuotaEligibility:
    """Decide whether ``quota`` may be queried for one train run and class at ``now``.

    ``rule`` is ``None`` for quotas without a booking window (General). ``boarding_date`` is only
    used to detect a past journey; the window itself depends on ``train_origin_date`` alone.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    category = class_category(travel_class)

    def result(state: QuotaEligibilityState, opens_at: datetime | None = None) -> QuotaEligibility:
        return QuotaEligibility(quota, travel_class, state, category, train_origin_date, opens_at)

    if not provider_supported:
        return result(QuotaEligibilityState.PROVIDER_UNSUPPORTED)
    if rule is None:
        return result(QuotaEligibilityState.NOT_APPLICABLE)
    if category is None:
        return result(QuotaEligibilityState.CLASS_CATEGORY_UNKNOWN)
    if (
        train_origin_date is None
        or boarding_date is None
        or boarding_date < train_origin_date  # a train cannot board before it starts
    ):
        return result(QuotaEligibilityState.UNDETERMINED)

    today = today_ist(now)
    if boarding_date < today:
        return result(QuotaEligibilityState.JOURNEY_DATE_PASSED)

    opening_day = date.fromordinal(train_origin_date.toordinal() - rule.days_before)
    opens_at = ist_datetime(opening_day, rule.opening_time(category))
    if now < opens_at:
        state = (
            QuotaEligibilityState.OPENS_TODAY
            if opening_day == today
            else QuotaEligibilityState.NOT_YET_OPEN
        )
        return result(state, opens_at)
    if today < train_origin_date:
        return result(QuotaEligibilityState.OPEN, opens_at)
    return result(QuotaEligibilityState.OPENING_PASSED, opens_at)


def _when(moment: datetime) -> str:
    return moment.astimezone(IST).strftime("%d %b %Y at %H:%M IST")


def describe_eligibility(eligibility: QuotaEligibility) -> str:
    """One user-facing sentence. Never claims availability."""
    quota = eligibility.quota
    name = f"{quota.label} ({quota.value})"
    cls = eligibility.travel_class
    state = eligibility.state
    origin = (
        eligibility.train_origin_date.strftime("%d %b %Y")
        if eligibility.train_origin_date
        else None
    )
    opens = _when(eligibility.opens_at) if eligibility.opens_at else None
    states = QuotaEligibilityState
    if state is states.NOT_APPLICABLE:
        return f"{name}: no booking-window restriction applies."
    if state is states.PROVIDER_UNSUPPORTED:
        return (
            f"{name} is not supported by the railway data provider, so it was not checked. "
            "No other quota was substituted."
        )
    if state is states.CLASS_CATEGORY_UNKNOWN:
        return (
            f"{name} was not checked for class {cls}: its AC/non-AC category is unknown, so the "
            "booking opening time cannot be determined."
        )
    if state is states.UNDETERMINED:
        return (
            f"{name} was not checked for class {cls}: the train's origin date could not be "
            "determined, so the booking opening time is unknown."
        )
    if state is states.JOURNEY_DATE_PASSED:
        return f"{name} was not checked for class {cls}: the journey date has passed."
    if state is states.NOT_YET_OPEN:
        return (
            f"{name} booking for class {cls} opens on {opens} (the train leaves its origin "
            f"station on {origin}). Not checked yet — search again after it opens."
        )
    if state is states.OPENS_TODAY:
        return (
            f"{name} booking for class {cls} opens today, {opens}. Not checked yet — search "
            "again after it opens."
        )
    if state is states.OPEN:
        return f"{name} booking for class {cls} is open (opened on {opens})."
    return (
        f"{name} booking for class {cls} opened on {opens} and can stay open until the chart is "
        "prepared."
    )
