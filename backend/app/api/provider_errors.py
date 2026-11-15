"""Translate provider / persistence failures into the public error envelope (doc 05 §7).

Provider credentials problems surface as a generic 503: clients never learn auth details.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.errors import error_payload
from app.core.errors import (
    AppError,
    NotFoundError,
    ProviderBadResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
    SemanticValidationError,
    ServiceUnavailableError,
)
from app.providers.errors import ProviderError, ProviderErrorCategory
from app.repositories.base import PersistenceError

logger = logging.getLogger(__name__)


def to_app_error(error: ProviderError) -> AppError:
    retry = (
        {"Retry-After": str(max(1, round(error.retry_after_seconds)))}
        if error.retry_after_seconds
        else None
    )
    match error.category:
        case ProviderErrorCategory.TIMEOUT:
            return ProviderTimeoutError()
        case ProviderErrorCategory.RATE_LIMITED:
            return RateLimitedError(
                "The railway data provider is rate-limiting requests. Try again later.",
                code="PROVIDER_RATE_LIMITED",
                headers=retry,
            )
        case ProviderErrorCategory.QUOTA_EXHAUSTED:
            return RateLimitedError(
                "The service has reached its railway data request limit. Try again later.",
                code="PROVIDER_QUOTA_EXHAUSTED",
                headers=retry,
            )
        case ProviderErrorCategory.AUTH:
            return ProviderUnavailableError()
        case ProviderErrorCategory.NOT_FOUND:
            return NotFoundError("The provider has no record for this request.", code="NOT_FOUND")
        case ProviderErrorCategory.REJECTED:
            return SemanticValidationError(
                "The provider rejected this request (for example, the train may not serve this "
                "station pair, class or date).",
                code="PROVIDER_REJECTED_REQUEST",
            )
        case ProviderErrorCategory.INVALID_RESPONSE:
            return ProviderBadResponseError(code="PROVIDER_INVALID_RESPONSE")
        case _:
            return ProviderBadResponseError(
                "The railway data provider failed to answer.", code="PROVIDER_UPSTREAM_ERROR"
            )


def install_provider_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProviderError)
    async def _provider(_: Request, exc: ProviderError) -> JSONResponse:
        logger.warning(
            "provider error",
            extra={"category": exc.category.value, "endpoint": exc.endpoint, "error": exc.message},
        )
        mapped = to_app_error(exc)
        return JSONResponse(
            error_payload(mapped.code, mapped.message),
            status_code=mapped.http_status,
            headers=mapped.headers,
        )

    @app.exception_handler(PersistenceError)
    async def _persistence(_: Request, exc: PersistenceError) -> JSONResponse:
        logger.error("persistence error", extra={"error": str(exc)})
        mapped = ServiceUnavailableError()
        return JSONResponse(error_payload(mapped.code, mapped.message), status_code=503)
