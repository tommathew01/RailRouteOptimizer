"""Operator endpoints: Prometheus metrics and provider quota usage (token protected)."""

from __future__ import annotations

import hmac
from dataclasses import asdict

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.deps import ContainerDep
from app.api.rate_limit import client_address
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


@router.get("/ops/client-address")
async def client_address_chain(request: Request, container: ContainerDep) -> dict[str, object]:
    """Which address the per-client API rate limit uses (token protected).

    Hosting platforms differ in how they build ``X-Forwarded-For``; call this once through the
    public URL after deploying and set ``TRUSTED_PROXY_HOPS`` so that ``client_address`` is your
    own public IP (runbook §4, docs/11).
    """
    authorize(request, container.settings)
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = container.settings.trusted_proxy_hops
    return {
        "x_forwarded_for": [part.strip() for part in forwarded.split(",") if part.strip()],
        "socket_peer": request.client.host if request.client else None,
        "trusted_proxy_hops": hops,
        "client_address": client_address(request, hops),
    }
