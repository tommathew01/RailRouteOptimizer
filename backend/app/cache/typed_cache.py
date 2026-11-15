"""Typed JSON cache over a :class:`KeyValueStore` (domain dataclasses via Pydantic TypeAdapter).

Cache failures never break a request: read errors behave as misses, write errors are logged.
Undecodable entries (e.g. after a schema change) are deleted and treated as misses.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TypeVar

from pydantic import TypeAdapter, ValidationError

from app.cache.store import KeyValueStore, StoreError

logger = logging.getLogger(__name__)
T = TypeVar("T")


class TypedCache:
    def __init__(self, store: KeyValueStore) -> None:
        self._store = store

    @property
    def store(self) -> KeyValueStore:
        return self._store

    async def get(self, key: str, adapter: TypeAdapter[T]) -> T | None:
        try:
            raw = await self._store.get(key)
        except StoreError as exc:
            logger.warning("cache read failed", extra={"cache_key": key, "error": str(exc)})
            return None
        if raw is None:
            return None
        try:
            return adapter.validate_json(raw)
        except ValidationError:
            logger.warning("discarding undecodable cache entry", extra={"cache_key": key})
            with contextlib.suppress(StoreError):
                await self._store.delete(key)
            return None

    async def set(self, key: str, value: T, adapter: TypeAdapter[T], ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        try:
            await self._store.set(key, adapter.dump_json(value), ttl_seconds=ttl_seconds)
        except StoreError as exc:
            logger.warning("cache write failed", extra={"cache_key": key, "error": str(exc)})
