"""FastAPI dependencies. Routes stay thin: they resolve services from the container."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from app.container import AppContainer
from app.core.errors import RailwayMaintenanceError


def get_container(request: Request) -> AppContainer:
    return cast(AppContainer, request.app.state.container)


ContainerDep = Annotated[AppContainer, Depends(get_container)]


class RateLimit:
    """Per-client limit for a bucket: ``search`` (spends provider budget) or ``lookup``."""

    def __init__(self, bucket: str) -> None:
        self.bucket = bucket

    async def __call__(self, request: Request) -> None:
        await get_container(request).rate_limiter.check(request, self.bucket)


search_rate_limit = Depends(RateLimit("search"))
lookup_rate_limit = Depends(RateLimit("lookup"))


async def _railway_services_open(request: Request) -> None:
    """Refuse new train/availability work during the IRCTC maintenance window (D-31).

    Applied to every route that can make a train or availability request to the provider.
    Stored results (``GET /journeys/{id}``), stations and metadata stay available.
    """
    container = get_container(request)
    window = container.settings.maintenance_window
    now = container.clock.now()
    if window is None or not window.active(now):
        return
    reopens = window.ends_at(now)
    seconds = max(1, int((reopens - now).total_seconds())) if reopens else None
    raise RailwayMaintenanceError(
        window.describe(),
        details={
            "window_start": window.starts.strftime("%H:%M"),
            "window_end": window.ends.strftime("%H:%M"),
            "timezone": "Asia/Kolkata",
            "available_at": reopens.isoformat() if reopens else None,
        },
        headers={"Retry-After": str(seconds)} if seconds else None,
    )


#: Must come before the rate limits: a refused request spends nothing.
railway_services_open = Depends(_railway_services_open)
