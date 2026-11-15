"""Tatkal booking-window eligibility (docs/08 D-21)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.domain.enums import KNOWN_CLASS_CODES, Quota
from app.domain.quota_eligibility import (
    CLASS_CATEGORIES,
    QUERYABLE_STATES,
    ClassCategory,
    OpeningRule,
    QuotaEligibilityState,
    class_category,
    describe_eligibility,
    evaluate_quota_eligibility,
)
from app.domain.time import IST

State = QuotaEligibilityState
TATKAL = OpeningRule(days_before=1, ac_opens_at=time(10, 0), non_ac_opens_at=time(11, 0))
ORIGIN = date(2026, 11, 20)


def ist(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=IST)


def evaluate(
    now: datetime,
    *,
    cls: str = "3A",
    origin: date | None = ORIGIN,
    boarding: date | None = ORIGIN,
    quota: Quota = Quota.TATKAL,
    rule: OpeningRule | None = TATKAL,
    supported: bool = True,
) -> State:
    return evaluate_quota_eligibility(
        quota=quota,
        travel_class=cls,
        train_origin_date=origin,
        boarding_date=boarding,
        now=now,
        rule=rule,
        provider_supported=supported,
    ).state


# --- Opening-time boundaries (one second either side) ---------------------------------------------
@pytest.mark.parametrize(
    ("cls", "opening_hour"),
    [("3A", 10), ("2A", 10), ("1A", 10), ("CC", 10), ("3E", 10), ("SL", 11), ("2S", 11)],
)
def test_window_opens_exactly_at_the_class_category_time(cls: str, opening_hour: int) -> None:
    opens = ist(2026, 11, 19, opening_hour)
    assert evaluate(opens - timedelta(seconds=1), cls=cls) is State.OPENS_TODAY
    assert evaluate(opens, cls=cls) is State.OPEN
    assert evaluate(opens + timedelta(seconds=1), cls=cls) is State.OPEN


def test_non_ac_is_still_closed_when_ac_opens() -> None:
    at_ten = ist(2026, 11, 19, 10, 0)
    assert evaluate(at_ten, cls="3A") is State.OPEN
    assert evaluate(at_ten, cls="SL") is State.OPENS_TODAY


def test_days_before_the_opening_day_are_not_yet_open() -> None:
    assert evaluate(ist(2026, 11, 18, 23, 59, 59)) is State.NOT_YET_OPEN
    assert evaluate(ist(2026, 11, 8, 15, 30)) is State.NOT_YET_OPEN


def test_open_until_the_origin_date_then_opening_passed() -> None:
    assert evaluate(ist(2026, 11, 19, 23, 59, 59)) is State.OPEN
    assert evaluate(ist(2026, 11, 20, 0, 0, 0)) is State.OPENING_PASSED  # still queryable
    assert evaluate(ist(2026, 11, 20, 18, 0)) is State.OPENING_PASSED


def test_opening_details_are_reported() -> None:
    result = evaluate_quota_eligibility(
        quota=Quota.TATKAL,
        travel_class="SL",
        train_origin_date=ORIGIN,
        boarding_date=ORIGIN,
        now=ist(2026, 11, 8, 12, 0),
        rule=TATKAL,
        provider_supported=True,
    )
    assert result.opens_at == ist(2026, 11, 19, 11, 0)
    assert result.class_category is ClassCategory.NON_AC
    assert result.train_origin_date == ORIGIN
    assert result.awaiting_opening
    assert not result.queryable


# --- Time zones -----------------------------------------------------------------------------------
def test_utc_and_foreign_clocks_are_converted_to_ist() -> None:
    # 10:00 IST on 19 Nov is 04:30 UTC.
    assert evaluate(datetime(2026, 11, 19, 4, 29, 59, tzinfo=UTC)) is State.OPENS_TODAY
    assert evaluate(datetime(2026, 11, 19, 4, 30, 0, tzinfo=UTC)) is State.OPEN
    new_york = datetime(2026, 11, 18, 23, 30, tzinfo=ZoneInfo("America/New_York"))  # 04:30 UTC
    assert evaluate(new_york) is State.OPEN


def test_ist_calendar_day_not_utc_day_decides_opens_today() -> None:
    # 18:30 UTC on 18 Nov is already 00:00 IST on 19 Nov (the opening day).
    assert evaluate(datetime(2026, 11, 18, 18, 30, tzinfo=UTC)) is State.OPENS_TODAY
    assert evaluate(datetime(2026, 11, 18, 18, 29, 59, tzinfo=UTC)) is State.NOT_YET_OPEN


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate(datetime(2026, 11, 19, 10, 0))  # noqa: DTZ001 (deliberately naive)


# --- Day / month / year / leap-day boundaries -----------------------------------------------------
@pytest.mark.parametrize(
    ("origin", "opening_day"),
    [
        (date(2026, 12, 1), date(2026, 11, 30)),  # month boundary
        (date(2027, 1, 1), date(2026, 12, 31)),  # year boundary
        (date(2028, 3, 1), date(2028, 2, 29)),  # leap year
        (date(2027, 3, 1), date(2027, 2, 28)),  # non-leap year
    ],
)
def test_opening_day_crosses_calendar_boundaries(origin: date, opening_day: date) -> None:
    opens = datetime.combine(opening_day, time(10, 0), tzinfo=IST)
    assert evaluate(opens - timedelta(seconds=1), origin=origin, boarding=origin) is (
        State.OPENS_TODAY
    )
    assert evaluate(opens, origin=origin, boarding=origin) is State.OPEN


def test_days_before_is_configurable() -> None:
    two_days = OpeningRule(days_before=2, ac_opens_at=time(10, 0), non_ac_opens_at=time(11, 0))
    assert evaluate(ist(2026, 11, 18, 10, 0), rule=two_days) is State.OPEN
    assert evaluate(ist(2026, 11, 18, 9, 59, 59), rule=two_days) is State.OPENS_TODAY
    with pytest.raises(ValueError, match="days_before"):
        OpeningRule(days_before=-1, ac_opens_at=time(10), non_ac_opens_at=time(11))


# --- Origin date, never the boarding date ---------------------------------------------------------
def test_boarding_after_midnight_uses_the_origin_date() -> None:
    # Train starts 20 Nov; the passenger boards on route day 2 (21 Nov). Tatkal opens on 19 Nov.
    now = ist(2026, 11, 19, 10, 0)
    assert evaluate(now, origin=ORIGIN, boarding=date(2026, 11, 21)) is State.OPEN
    # Had the boarding date been used, it would wrongly still be closed until 20 Nov 10:00.
    assert evaluate(now, origin=date(2026, 11, 21), boarding=date(2026, 11, 21)) is (
        State.NOT_YET_OPEN
    )


def test_train_already_running_from_yesterday_is_opening_passed_not_journey_passed() -> None:
    now = ist(2026, 11, 21, 6, 0)
    assert evaluate(now, origin=ORIGIN, boarding=date(2026, 11, 21)) is State.OPENING_PASSED


# --- Not determinable / not applicable ------------------------------------------------------------
def test_past_journey_date() -> None:
    assert evaluate(ist(2026, 11, 21, 0, 0), boarding=ORIGIN) is State.JOURNEY_DATE_PASSED


@pytest.mark.parametrize(
    ("origin", "boarding"),
    [(None, ORIGIN), (ORIGIN, None), (None, None), (ORIGIN, date(2026, 11, 19))],
)
def test_missing_or_inconsistent_dates_are_undetermined(
    origin: date | None, boarding: date | None
) -> None:
    assert evaluate(ist(2026, 11, 19, 12, 0), origin=origin, boarding=boarding) is (
        State.UNDETERMINED
    )


@pytest.mark.parametrize("cls", ["CH", "HS", "VC", "XX", ""])
def test_unknown_classes_are_never_classified(cls: str) -> None:
    assert class_category(cls) is None
    assert evaluate(ist(2026, 11, 19, 12, 0), cls=cls) is State.CLASS_CATEGORY_UNKNOWN


def test_general_quota_has_no_window_even_for_unknown_classes() -> None:
    for cls in ("3A", "CH"):
        assert evaluate(ist(2026, 11, 8, 1, 0), cls=cls, quota=Quota.GENERAL, rule=None) is (
            State.NOT_APPLICABLE
        )


def test_provider_support_is_checked_first() -> None:
    now = ist(2026, 11, 19, 12, 0)
    assert evaluate(now, supported=False) is State.PROVIDER_UNSUPPORTED
    assert evaluate(now, origin=None, supported=False) is State.PROVIDER_UNSUPPORTED


def test_configured_opening_times_are_respected() -> None:
    later = OpeningRule(days_before=1, ac_opens_at=time(10, 30), non_ac_opens_at=time(11, 30))
    now = ist(2026, 11, 19, 10, 15)
    assert evaluate(now, rule=later) is State.OPENS_TODAY
    assert evaluate(now) is State.OPEN  # default 10:00 rule


def test_only_open_and_general_states_are_queryable() -> None:
    assert {
        State.NOT_APPLICABLE,
        State.OPEN,
        State.OPENING_PASSED,
    } == QUERYABLE_STATES


# --- Class mapping guard and messages -------------------------------------------------------------
def test_every_class_code_is_classified_or_deliberately_unclassified() -> None:
    deliberately_unclassified = {"VC", "CH", "HS"}
    assert set(CLASS_CATEGORIES) | deliberately_unclassified == KNOWN_CLASS_CODES
    assert not set(CLASS_CATEGORIES) & deliberately_unclassified


def test_messages_state_opening_time_and_never_claim_unavailability() -> None:
    messages = []
    cases: list[tuple[datetime, dict[str, Any]]] = [
        (ist(2026, 11, 8, 12, 0), {}),
        (ist(2026, 11, 19, 9, 0), {}),
        (ist(2026, 11, 19, 12, 0), {}),
        (ist(2026, 11, 20, 12, 0), {}),
        (ist(2026, 11, 21, 12, 0), {}),
        (ist(2026, 11, 19, 12, 0), {"travel_class": "CH"}),
        (ist(2026, 11, 19, 12, 0), {"train_origin_date": None}),
        (ist(2026, 11, 19, 12, 0), {"provider_supported": False}),
    ]
    for now, kwargs in cases:
        arguments: dict[str, Any] = {
            "quota": Quota.TATKAL,
            "travel_class": "3A",
            "train_origin_date": ORIGIN,
            "boarding_date": ORIGIN,
            "rule": TATKAL,
            "provider_supported": True,
        }
        arguments.update(kwargs)
        messages.append(describe_eligibility(evaluate_quota_eligibility(now=now, **arguments)))
    assert "opens on 19 Nov 2026 at 10:00 IST" in messages[0]
    assert "opens today, 19 Nov 2026 at 10:00 IST" in messages[1]
    assert "No other quota was substituted" in messages[-1]
    for message in messages:
        assert "Tatkal (TQ)" in message
        assert "unavailable" not in message.lower()
        assert "not available" not in message.lower()
