"""Provider request budgets (doc 04 §7; decision D-07).

* :class:`ProviderQuotaGuard` — global, shared across processes via the store: a fixed window
  (default 100 / 10 min) and a calendar-month cap (IST), checked before *every* HTTP attempt,
  plus a shared back-off after a provider 429. If the store fails, provider calls fail closed.
* :class:`SearchBudget` — per-search cap on provider availability calls (cache hits are free).
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
    """Counts provider availability calls for one search; safe under concurrent use."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0
        self._lock = asyncio.Lock()

    async def try_consume(self) -> bool:
        async with self._lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True

    async def refund(self) -> None:
        async with self._lock:
            self.used = max(0, self.used - 1)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)
