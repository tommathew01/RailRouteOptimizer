"""FastAPI application factory. Import-safe: building the app does not read the environment."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.provider_errors import install_provider_error_handlers
from app.api.v1.router import api_router
from app.container import AppContainer
from app.core.config import Settings

ContainerFactory = Callable[[Settings], Awaitable[AppContainer]]

API_DESCRIPTION = """
Same-train segment availability discovery for Indian Railways.

* Every recommendation uses **one train, one journey, one class and one quota** (GN or TQ;
  quotas are never mixed). Tatkal is only queried once its booking window opens.
* A recommendation of *n* segments means **n separate tickets** (possibly *n* PNRs).
* Current availability and RailKit's optional prediction are always reported separately.
* Searches may be **partial**; `search_completeness` and `coverage` state what was checked.
"""


def create_app(settings: Settings, *, container_factory: ContainerFactory | None = None) -> FastAPI:
    factory = container_factory or AppContainer.build

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = await factory(settings)
        app.state.container = container
        try:
            yield
        finally:
            await container.aclose()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        allow_credentials=False,
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_request_body_bytes)
    install_error_handlers(app)
    install_provider_error_handlers(app)
    app.include_router(api_router)
    return app
