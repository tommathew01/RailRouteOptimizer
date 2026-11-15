"""Opt-in infrastructure fixtures. Set TEST_DATABASE_URL (owner role) and/or TEST_REDIS_URL.

The database named in TEST_DATABASE_URL is created if missing, migrated to head before the
tests and downgraded to base afterwards. Never point it at a database you care about.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from app.cache.store import RedisStore
from app.core.config import BACKEND_DIR
from app.database.session import create_engine
from app.repositories.sqlalchemy import SqlAlchemyPersistence

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
REDIS_URL = os.environ.get("TEST_REDIS_URL")

requires_db = pytest.mark.skipif(not DATABASE_URL, reason="set TEST_DATABASE_URL to run")
requires_redis = pytest.mark.skipif(not REDIS_URL, reason="set TEST_REDIS_URL to run")


def _libpq(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


async def _ensure_database(url: str) -> None:
    parts = urlsplit(_libpq(url))
    name = parts.path.lstrip("/")
    admin_url = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, ""))
    async with await psycopg.AsyncConnection.connect(admin_url, autocommit=True) as conn:
        cur = await conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if await cur.fetchone() is None:
            await conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _alembic(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    return config


@pytest.fixture
async def persistence() -> AsyncIterator[SqlAlchemyPersistence]:
    assert DATABASE_URL is not None
    await _ensure_database(DATABASE_URL)
    config = _alembic(DATABASE_URL)
    await asyncio.to_thread(command.downgrade, config, "base")
    await asyncio.to_thread(command.upgrade, config, "head")
    gateway = SqlAlchemyPersistence(create_engine(DATABASE_URL, pool_size=2, max_overflow=0))
    try:
        yield gateway
    finally:
        await gateway.aclose()
        await asyncio.to_thread(command.downgrade, config, "base")


@pytest.fixture
async def redis_store() -> AsyncIterator[RedisStore]:
    assert REDIS_URL is not None
    store = RedisStore.from_url(REDIS_URL)
    await store._redis.flushdb()  # TEST_REDIS_URL must be a dedicated database number
    try:
        yield store
    finally:
        await store._redis.flushdb()
        await store.aclose()
