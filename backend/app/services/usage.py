"""Provider usage accounting: buffered ``provider_usage`` rows + metrics, and observer fan-out."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Sequence

from app.core import metrics
from app.core.clock import Clock
from app.core.context import search_id_var
from app.providers.base import ProviderRequestEvent, ProviderRequestObserver
from app.repositories.base import Persistence, PersistenceError
from app.repositories.records import ProviderUsageRecord

logger = logging.getLogger(__name__)


class CompositeObserver:
    """Runs observers in order. ``before_request`` failures (quota refusals) propagate."""

    def __init__(self, observers: Sequence[ProviderRequestObserver]) -> None:
        self._observers = list(observers)

    async def before_request(self, provider: str, endpoint: str) -> None:
        for observer in self._observers:
            await observer.before_request(provider, endpoint)

    async def after_request(self, event: ProviderRequestEvent) -> None:
        for observer in self._observers:
            try:
                await observer.after_request(event)
            except Exception:
                logger.exception("provider observer failed")


class ProviderUsageRecorder:
    """Buffers one row per provider HTTP attempt and flushes them in batches."""

    def __init__(self, persistence: Persistence, *, clock: Clock, max_buffer: int = 500) -> None:
        self._persistence = persistence
        self._clock = clock
        self._buffer: list[ProviderUsageRecord] = []
        self._max_buffer = max_buffer
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    async def before_request(self, provider: str, endpoint: str) -> None:
        return None

    async def after_request(self, event: ProviderRequestEvent) -> None:
        metrics.PROVIDER_REQUESTS.labels(event.provider, event.endpoint, event.outcome).inc()
        metrics.PROVIDER_LATENCY.labels(event.provider, event.endpoint).observe(
            event.latency_ms / 1000
        )
        search_id = search_id_var.get()
        self._buffer.append(
            ProviderUsageRecord(
                id=uuid.uuid4(),
                provider=event.provider,
                endpoint=event.endpoint,
                outcome=event.outcome,
                attempt=event.attempt,
                created_at=self._clock.now(),
                status_code=event.status_code,
                latency_ms=event.latency_ms,
                search_id=uuid.UUID(search_id) if search_id else None,
            )
        )
        if len(self._buffer) >= self._max_buffer:
            await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            batch, self._buffer = self._buffer, []
            try:
                await self._persistence.add_provider_usage(batch)
            except PersistenceError:
                logger.warning("could not persist provider usage", extra={"rows": len(batch)})
                self._buffer = (batch + self._buffer)[-self._max_buffer :]

    def start(self, interval_seconds: float = 5.0) -> None:
        async def loop() -> None:
            while True:
                await asyncio.sleep(interval_seconds)
                await self.flush()

        self._task = asyncio.create_task(loop(), name="provider-usage-flusher")

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.flush()
