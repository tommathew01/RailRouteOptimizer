"""Operator endpoints: Prometheus metrics and provider quota usage (token protected)."""

from __future__ import annotations

import hmac
from dataclasses import asdict

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.deps import ContainerDep
from app.core import metrics
from app.core.config import Environment, Settings
from app.core.errors import NotFoundError, UnauthenticatedError

router = APIRouter(include_in_schema=False)


def authorize(request: Request, settings: Settings) -> None:
    if not settings.metrics_enabled:
        raise NotFoundError()
    token = settings.metrics_token
    if token is None:
        if settings.environment in (Environment.DEVELOPMENT, Environment.TEST):
            return
        raise NotFoundError()  # never expose operator data without a configured token
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied.encode(), f"Bearer {token.get_secret_value()}".encode()):
        raise UnauthenticatedError(headers={"WWW-Authenticate": "Bearer"})


@router.get("/metrics")
async def prometheus_metrics(request: Request, container: ContainerDep) -> Response:
    authorize(request, container.settings)
    return Response(generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)


@router.get("/ops/provider-quota")
async def provider_quota(request: Request, container: ContainerDep) -> dict[str, object]:
    authorize(request, container.settings)
    snapshot = await container.quota_guard.snapshot(container.provider.name)
    return {"provider": container.provider.name, **asdict(snapshot)}
