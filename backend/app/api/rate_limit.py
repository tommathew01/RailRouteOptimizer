"""Per-client fixed-window API rate limits (doc 04 §7 "per-user rate limit").

Clients are identified by IP. With ``TRUSTED_PROXY_HOPS=n`` the n-th address from the right of
``X-Forwarded-For`` is used (the one written by the outermost trusted proxy); otherwise the socket
peer. Addresses are hashed before use as keys. Store failures fail *open* here — provider quota
guards still protect the RailKit budget independently.
"""

from __future__ import annotations

import hashlib
import logging
import time

from fastapi import Request

from app.cache.store import KeyValueStore, StoreError
from app.core.errors import RateLimitedError

logger = logging.getLogger(__name__)


def client_address(request: Request, trusted_hops: int) -> str:
    if trusted_hops > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(chain) >= trusted_hops:
            return chain[-trusted_hops]
    return request.client.host if request.client else "unknown"


class ApiRateLimiter:
    def __init__(
        self,
        store: KeyValueStore,
        *,
        window_seconds: int,
        limits: dict[str, int],
        trusted_hops: int,
    ) -> None:
        self._store = store
        self._window = window_seconds
        self._limits = limits
        self._hops = trusted_hops

    async def check(self, request: Request, bucket: str) -> None:
        limit = self._limits[bucket]
        address = client_address(request, self._hops)
        digest = hashlib.sha256(address.encode()).hexdigest()[:24]
        window = int(time.time()) // self._window
        key = f"ratelimit:{bucket}:{digest}:{window}"
        try:
            count = await self._store.incr(key, ttl_seconds=self._window)
        except StoreError:
            logger.warning("rate limiter unavailable; allowing request")
            return
        if count > limit:
            retry_after = self._window - int(time.time()) % self._window
            raise RateLimitedError(headers={"Retry-After": str(max(1, retry_after))})
