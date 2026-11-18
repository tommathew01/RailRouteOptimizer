"""Provider request budgets (doc 04 §7; decision D-07).

* :class:`ProviderQuotaGuard` — global, shared across processes via the store: a fixed window
  (default 100 / 10 min) and a calendar-month cap (IST), checked before *every* HTTP attempt,
  plus a shared back-off after a provider 429. If the store fails, provider calls fail closed.
* :class:`SearchBudget` — per-search cap on provider availability *attempts*, retries included
  (cache hits are free; D-28).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.cache.store import KeyValueStore, StoreError
from app.core.clock import Clock
from app.domain.time import IST
from app.providers.base import ProviderRequestEvent
from app.providers.errors import ProviderErrorCategory, ProviderQuotaExhaustedError

logger = logging.getLogger(__name__)

MONTH_KEY_TTL_SECONDS = 40 * 24 * 3600


class QuotaRefusal:
    WINDOW = "WINDOW_LIMIT"
    MONTHLY = "MONTHLY_LIMIT"
    BACKOFF = "PROVIDER_BACKOFF"
    GUARD_UNAVAILABLE = "GUARD_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    window_used: int
    window_limit: int
    window_seconds: int
    monthly_used: int
    monthly_limit: int
    backoff_seconds_remaining: float | None


class ProviderQuotaGuard:
    def __init__(
        self,
        store: KeyValueStore,
        *,
        clock: Clock,
        window_limit: int,
        window_seconds: int,
        monthly_limit: int,
        backoff_seconds: int,
    ) -> None:
        self._store = store
        self._clock = clock
        self._window_limit = window_limit
        self._window_seconds = window_seconds
        self._monthly_limit = monthly_limit
        self._backoff_seconds = backoff_seconds

    def _window_key(self, provider: str) -> str:
        bucket = int(self._clock.now().timestamp()) // self._window_seconds
        return f"quota:{provider}:window:{self._window_seconds}:{bucket}"

    def _month_key(self, provider: str) -> str:
        return f"quota:{provider}:month:{self._clock.now().astimezone(IST):%Y-%m}"

    @staticmethod
    def _backoff_key(provider: str) -> str:
        return f"quota:{provider}:backoff"

    def _refuse(self, provider: str, endpoint: str, reason: str, retry_after: float | None) -> None:
        logger.warning(
            "provider call refused by quota guard",
            extra={"provider": provider, "endpoint": endpoint, "reason": reason},
        )
        raise ProviderQuotaExhaustedError(
            reason,
            provider=provider,
            endpoint=endpoint,
            retry_after_seconds=retry_after,
            diagnostics={"reason": reason},
        )

    async def before_request(self, provider: str, endpoint: str) -> None:
        window_key, month_key = self._window_key(provider), self._month_key(provider)
        try:
            if await self._store.get(self._backoff_key(provider)) is not None:
                remaining = await self._store.ttl(self._backoff_key(provider))
                self._refuse(provider, endpoint, QuotaRefusal.BACKOFF, remaining)
            window = await self._store.incr(window_key, ttl_seconds=self._window_seconds)
            if window > self._window_limit:
                await self._store.incr(window_key, -1)
                self._refuse(
                    provider, endpoint, QuotaRefusal.WINDOW, await self._store.ttl(window_key)
                )
            month = await self._store.incr(month_key, ttl_seconds=MONTH_KEY_TTL_SECONDS)
            if month > self._monthly_limit:
                await self._store.incr(month_key, -1)
                await self._store.incr(window_key, -1)
                self._refuse(provider, endpoint, QuotaRefusal.MONTHLY, None)
        except StoreError:
            self._refuse(provider, endpoint, QuotaRefusal.GUARD_UNAVAILABLE, None)

    async def after_request(self, event: ProviderRequestEvent) -> None:
        if event.outcome != ProviderErrorCategory.RATE_LIMITED.value:
            return
        seconds = event.retry_after_seconds or self._backoff_seconds
        try:
            await self._store.set(
                self._backoff_key(event.provider), b"1", ttl_seconds=max(1.0, seconds)
            )
        except StoreError:
            logger.warning("could not record provider back-off")

    async def snapshot(self, provider: str) -> QuotaSnapshot:
        async def read(key: str) -> int:
            raw = await self._store.get(key)
            return int(raw) if raw is not None else 0

        backoff = await self._store.ttl(self._backoff_key(provider))
        return QuotaSnapshot(
            window_used=await read(self._window_key(provider)),
            window_limit=self._window_limit,
            window_seconds=self._window_seconds,
            monthly_used=await read(self._month_key(provider)),
            monthly_limit=self._monthly_limit,
            backoff_seconds_remaining=backoff,
        )


class SearchBudget:
    """Per-search cap on provider availability *attempts*; safe under concurrent use (D-28).

    One unit pays for one provider attempt. A logical availability check reserves its first
    attempt before the call (:meth:`start_call`); every retry reserves one more unit through the
    call's gate, and is refused when the budget is spent. After the call the reservation is settled
    against the attempts actually made, so a guard refusal costs nothing and a retry is never
    free. Cache hits and shared single-flight results never reserve anything.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        #: Units charged: attempts made plus reservations of calls still in flight.
        self.used = 0
        #: Logical availability checks that reached the provider (at least one attempt).
        self.checks = 0
        #: Provider attempts made (first attempts + retries) = HTTP requests for RailKit.
        self.attempts = 0
        #: Attempts beyond the first of a check.
        self.retries = 0
        #: Retries the provider client wanted but this budget could not pay for.
        self.retries_refused = 0
        #: Set when the user stops the search: nothing new may start (D-35).
        self.stopped = False
        self._lock = asyncio.Lock()

    def stop(self) -> None:
        """Refuse every new check, retry and not-yet-sent attempt from now on (idempotent)."""
        self.stopped = True

    async def try_consume(self, units: int = 1) -> bool:
        async with self._lock:
            if self.stopped or self.used + units > self.limit:
                return False
            self.used += units
            return True

    async def refund(self, units: int = 1) -> None:
        async with self._lock:
            self.used = max(0, self.used - units)

    async def _charge(self, units: int) -> None:
        """Record attempts that were made without a reservation (never refused: it happened)."""
        async with self._lock:
            self.used += units

    async def start_call(self) -> BudgetedCall | None:
        """Reserve the first attempt of one logical check; ``None`` when the budget is spent."""
        if not await self.try_consume():
            return None
        return BudgetedCall(self)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class BudgetedCall:
    """The :class:`~app.providers.base.ProviderCallGate` of one logical check on a budget."""

    def __init__(self, budget: SearchBudget) -> None:
        self._budget = budget
        self.reserved = 1
        self.attempts = 0
        self._settled = False

    def attempt_started(self) -> None:
        self.attempts += 1

    def may_start(self) -> bool:
        return not self._budget.stopped

    async def allow_retry(self) -> bool:
        if await self._budget.try_consume():
            self.reserved += 1
            return True
        self._budget.retries_refused += 1
        return False

    async def settle(self, *, reached_provider: bool) -> int:
        """Charge exactly the attempts made and return unused reservations. Idempotent.

        Adapters that do not report attempts (e.g. the mock provider) are counted as one attempt
        per call that reached the provider.
        """
        if self._settled:
            return self.attempts
        self._settled = True
        budget = self._budget
        attempts = self.attempts or (1 if reached_provider else 0)
        self.attempts = attempts
        if attempts:
            budget.checks += 1
            budget.attempts += attempts
            budget.retries += attempts - 1
        if attempts < self.reserved:
            await budget.refund(self.reserved - attempts)
        elif attempts > self.reserved:
            await budget._charge(attempts - self.reserved)
        return attempts
