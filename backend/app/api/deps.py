"""FastAPI dependencies. Routes stay thin: they resolve services from the container."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from app.container import AppContainer


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
