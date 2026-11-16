"""Reservation-quota eligibility: may RailRoute query a quota for a train run and class now?

Thin, reusable wrapper around :func:`app.domain.quota_eligibility.evaluate_quota_eligibility` that
supplies the configured opening rules, the provider's supported quotas and an injectable clock.
(Not to be confused with :mod:`app.services.quota`, the *provider request* quota guard.)
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from app.core.clock import Clock
from app.core.config import Settings
from app.domain.enums import QUOTA_ORDER, Quota
from app.domain.quota_eligibility import (
    OpeningRule,
    QuotaEligibility,
    evaluate_quota_eligibility,
)


class QuotaEligibilityService:
    def __init__(
        self, *, settings: Settings, clock: Clock, supported_quotas: Iterable[Quota]
    ) -> None:
        self._clock = clock
        self._supported = frozenset(supported_quotas)
        self._rules = {quota: settings.opening_rule(quota) for quota in QUOTA_ORDER}

    def now(self) -> datetime:
        return self._clock.now()

    def is_supported(self, quota: Quota) -> bool:
        return quota in self._supported

    @property
    def supported_quotas(self) -> frozenset[Quota]:
        return self._supported

    def rule(self, quota: Quota) -> OpeningRule | None:
        return self._rules[quota]

    def evaluate(
        self,
        quota: Quota,
        travel_class: str,
        *,
        train_origin_date: date | None,
        boarding_date: date | None,
        now: datetime | None = None,
    ) -> QuotaEligibility:
        """Pass one ``now`` for every combination of a search so all use the same instant."""
        return evaluate_quota_eligibility(
            quota=quota,
            travel_class=travel_class,
            train_origin_date=train_origin_date,
            boarding_date=boarding_date,
            now=now or self._clock.now(),
            rule=self._rules[quota],
            provider_supported=quota in self._supported,
        )
