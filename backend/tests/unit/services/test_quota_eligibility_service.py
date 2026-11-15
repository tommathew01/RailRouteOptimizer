from __future__ import annotations

from datetime import UTC, date, datetime

from app.core.clock import FrozenClock
from app.domain.enums import Quota
from app.domain.quota_eligibility import QuotaEligibilityState as State
from app.services.quota_eligibility import QuotaEligibilityService
from tests.conftest import make_settings

ORIGIN = date(2026, 11, 20)


def service(clock: FrozenClock, **settings: object) -> QuotaEligibilityService:
    return QuotaEligibilityService(
        settings=make_settings(**settings),
        clock=clock,
        supported_quotas=(Quota.GENERAL, Quota.TATKAL),
    )


def test_uses_the_injected_clock_and_configured_rules() -> None:
    clock = FrozenClock(datetime(2026, 11, 19, 4, 29, tzinfo=UTC))  # 09:59 IST
    eligibility = service(clock)
    tatkal = eligibility.evaluate(
        Quota.TATKAL, "3A", train_origin_date=ORIGIN, boarding_date=ORIGIN
    )
    assert tatkal.state is State.OPENS_TODAY
    clock.advance(60)  # 10:00 IST
    assert (
        eligibility.evaluate(Quota.TATKAL, "3A", train_origin_date=ORIGIN, boarding_date=ORIGIN)
    ).state is State.OPEN

    earlier = service(clock, tatkal_ac_opening_time="09:00")
    clock_value = datetime(2026, 11, 19, 3, 31, tzinfo=UTC)  # 09:01 IST
    assert (
        earlier.evaluate(
            Quota.TATKAL,
            "3A",
            train_origin_date=ORIGIN,
            boarding_date=ORIGIN,
            now=clock_value,
        ).state
        is State.OPEN
    )


def test_provider_support_and_general_quota() -> None:
    clock = FrozenClock(datetime(2026, 11, 19, 6, 0, tzinfo=UTC))
    eligibility = service(clock)
    assert eligibility.is_supported(Quota.TATKAL)
    assert eligibility.rule(Quota.GENERAL) is None
    general_only = QuotaEligibilityService(
        settings=make_settings(), clock=clock, supported_quotas=(Quota.GENERAL,)
    )
    assert not general_only.is_supported(Quota.TATKAL)
    tatkal = general_only.evaluate(
        Quota.TATKAL, "3A", train_origin_date=ORIGIN, boarding_date=ORIGIN
    )
    assert tatkal.state is State.PROVIDER_UNSUPPORTED
    assert not tatkal.queryable
    general = eligibility.evaluate(Quota.GENERAL, "CH", train_origin_date=None, boarding_date=None)
    assert general.state is State.NOT_APPLICABLE
    assert general.queryable
