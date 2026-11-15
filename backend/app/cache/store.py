"""Minimal key-value store used for caching, single-flight locks and counters.

``RedisStore`` is the production backend. ``MemoryStore`` is a single-process stand-in for tests
and zero-infrastructure demo mode; it is *not* safe across processes.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from redis.asyncio import Redis


class StoreError(Exception):
    """The backing store failed (connection refused, timeout, ...)."""


class KeyValueStore(Protocol):
    @property
    def distributed(self) -> bool: ...

    async def get(self, key: str) -> bytes | None: ...

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ttl_seconds: float | None = None,
        only_if_absent: bool = False,
    ) -> bool: ...

    async def delete(self, key: str) -> None: ...

    async def delete_if_equals(self, key: str, value: bytes) -> bool: ...

    async def incr(self, key: str, amount: int = 1, *, ttl_seconds: int | None = None) -> int:
        """Atomically add ``amount``; a newly created key gets ``ttl_seconds``."""
        ...

    async def ttl(self, key: str) -> float | None: ...

    async def ping(self) -> None: ...

    async def aclose(self) -> None: ...


class MemoryStore:
    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._data: dict[str, tuple[bytes, float | None]] = {}
        self._now = monotonic

    @property
    def distributed(self) -> bool:
        return False

    def _live(self, key: str) -> tuple[bytes, float | None] | None:
        item = self._data.get(key)
        if item is None:
            return None
        if item[1] is not None and item[1] <= self._now():
            del self._data[key]
            return None
        return item

    async def get(self, key: str) -> bytes | None:
        item = self._live(key)
        return None if item is None else item[0]

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ttl_seconds: float | None = None,
        only_if_absent: bool = False,
    ) -> bool:
        if only_if_absent and self._live(key) is not None:
            return False
        expires = None if ttl_seconds is None else self._now() + ttl_seconds
        self._data[key] = (value, expires)
        return True

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def delete_if_equals(self, key: str, value: bytes) -> bool:
        item = self._live(key)
        if item is not None and item[0] == value:
            del self._data[key]
            return True
        return False

    async def incr(self, key: str, amount: int = 1, *, ttl_seconds: int | None = None) -> int:
        item = self._live(key)
        if item is None:
            new_value = amount
            expires = None if ttl_seconds is None else self._now() + ttl_seconds
        else:
            new_value = int(item[0]) + amount
            expires = item[1]
        self._data[key] = (str(new_value).encode(), expires)
        return new_value

    async def ttl(self, key: str) -> float | None:
        item = self._live(key)
        if item is None or item[1] is None:
            return None
        return max(0.0, item[1] - self._now())

    async def ping(self) -> None:
        return None

    async def aclose(self) -> None:
        self._data.clear()


_COMPARE_AND_DELETE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class RedisStore:
    def __init__(self, client: Redis) -> None:
        self._redis = client
        self._compare_and_delete = client.register_script(_COMPARE_AND_DELETE)

    @classmethod
    def from_url(cls, url: str, *, timeout_seconds: float = 2.0) -> RedisStore:
        client = Redis.from_url(
            url,
            socket_timeout=timeout_seconds,
            socket_connect_timeout=timeout_seconds,
            health_check_interval=30,
        )
        return cls(client)

    @property
    def distributed(self) -> bool:
        return True

    async def get(self, key: str) -> bytes | None:
        try:
            value = await self._redis.get(key)
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc
        if value is None:
            return None
        return value.encode() if isinstance(value, str) else bytes(value)

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ttl_seconds: float | None = None,
        only_if_absent: bool = False,
    ) -> bool:
        try:
            px = None if ttl_seconds is None else max(1, int(ttl_seconds * 1000))
            result = await self._redis.set(key, value, px=px, nx=only_if_absent)
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc
        return bool(result)

    async def delete(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc

    async def delete_if_equals(self, key: str, value: bytes) -> bool:
        try:
            return bool(await self._compare_and_delete(keys=[key], args=[value]))
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc

    async def incr(self, key: str, amount: int = 1, *, ttl_seconds: int | None = None) -> int:
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incrby(key, amount)
                if ttl_seconds is not None:
                    pipe.expire(key, ttl_seconds, nx=True)
                results = await pipe.execute()
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc
        return int(results[0])

    async def ttl(self, key: str) -> float | None:
        try:
            millis = await self._redis.pttl(key)
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc
        return None if millis is None or millis < 0 else millis / 1000

    async def ping(self) -> None:
        try:
            await self._redis.ping()
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc

    async def aclose(self) -> None:
        await self._redis.aclose()


class NamespacedStore:
    """Prefixes every key (e.g. ``railroute:production:``) so environments never collide."""

    def __init__(self, inner: KeyValueStore, prefix: str) -> None:
        self._inner = inner
        self._prefix = prefix

    @property
    def distributed(self) -> bool:
        return self._inner.distributed

    def _k(self, key: str) -> str:
        return self._prefix + key

    async def get(self, key: str) -> bytes | None:
        return await self._inner.get(self._k(key))

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ttl_seconds: float | None = None,
        only_if_absent: bool = False,
    ) -> bool:
        return await self._inner.set(
            self._k(key), value, ttl_seconds=ttl_seconds, only_if_absent=only_if_absent
        )

    async def delete(self, key: str) -> None:
        await self._inner.delete(self._k(key))

    async def delete_if_equals(self, key: str, value: bytes) -> bool:
        return await self._inner.delete_if_equals(self._k(key), value)

    async def incr(self, key: str, amount: int = 1, *, ttl_seconds: int | None = None) -> int:
        return await self._inner.incr(self._k(key), amount, ttl_seconds=ttl_seconds)

    async def ttl(self, key: str) -> float | None:
        return await self._inner.ttl(self._k(key))

    async def ping(self) -> None:
        await self._inner.ping()

    async def aclose(self) -> None:
        await self._inner.aclose()
