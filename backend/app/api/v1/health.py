"""Liveness and readiness probes."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import ContainerDep
from app.schemas.common import ApiModel

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)

READINESS_TIMEOUT_SECONDS = 2.0


class LivenessResponse(ApiModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(ApiModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "failed"]]


@router.get("/live", response_model=LivenessResponse, summary="Process is running")
async def live() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Dependencies (database, Redis) are reachable",
    responses={503: {"model": ReadinessResponse}},
)
async def ready(container: ContainerDep) -> JSONResponse:
    results: dict[str, Literal["ok", "failed"]] = {}
    for name, check in container.readiness_checks.items():
        try:
            await asyncio.wait_for(check(), timeout=READINESS_TIMEOUT_SECONDS)
            results[name] = "ok"
        except Exception as exc:
            logger.warning(
                "readiness check failed", extra={"check": name, "error": type(exc).__name__}
            )
            results[name] = "failed"
    healthy = all(value == "ok" for value in results.values())
    body = ReadinessResponse(status="ready" if healthy else "not_ready", checks=results)
    return JSONResponse(body.model_dump(), status_code=200 if healthy else 503)
