"""API test harness: real app + lifespan, in-process ASGI transport, frozen clock."""

from __future__ import annotations

import functools
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.container import AppContainer
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.main import create_app
from app.providers.base import RailwayProvider
from tests.conftest import make_settings

NOW = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)
JOURNEY_DATE = date(2026, 11, 20)


@asynccontextmanager
async def api_client(
    settings: Settings | None = None,
    *,
    provider: RailwayProvider | None = None,
    **container_overrides: Any,
) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    factory = functools.partial(
        AppContainer.build, clock=FrozenClock(NOW), provider=provider, **container_overrides
    )
    application = create_app(settings or make_settings(), container_factory=factory)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http, application


@pytest.fixture
def api_settings() -> Settings:
    return make_settings()


@pytest.fixture
async def app(api_settings: Settings) -> AsyncIterator[FastAPI]:
    async with api_client(api_settings) as (_, application):
        yield application


@pytest.fixture
async def client(api_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with api_client(api_settings) as (http, _):
        yield http


def container_of(application: FastAPI) -> AppContainer:
    container: AppContainer = application.state.container
    return container


def optimize_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source": "TIR",
        "destination": "TVC",
        "journey_date": JOURNEY_DATE.isoformat(),
        "classes": ["3A"],
        "filters": {"allow_rac": True, "allow_waitlist": False},
    }
    body.update(overrides)
    return body
