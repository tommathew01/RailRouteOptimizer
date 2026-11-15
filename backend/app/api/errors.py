"""Exception handlers producing the doc-05 §7 error envelope."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware import RequestBodyTooLargeError
from app.core.context import request_id_var
from app.core.errors import AppError

logger = logging.getLogger(__name__)

_HTTP_CODES = {
    400: "INVALID_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "REQUEST_TOO_LARGE",
    429: "RATE_LIMITED",
}


def error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id_var.get()}
    if details:
        body["details"] = details
    return {"error": body}


def _validation_details(exc: RequestValidationError) -> dict[str, Any]:
    fields = []
    for err in exc.errors():
        location = [
            str(part) for part in err.get("loc", ()) if part not in ("body", "query", "path")
        ]
        fields.append(
            {
                "field": ".".join(location) or None,
                "message": err.get("msg"),
                "type": err.get("type"),
            }
        )
    return {"fields": fields}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.http_status >= 500:
            logger.warning("request failed", extra={"error_code": exc.code})
        return JSONResponse(
            error_payload(exc.code, exc.message, exc.details),
            status_code=exc.http_status,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            error_payload("INVALID_REQUEST", "The request is invalid.", _validation_details(exc)),
            status_code=400,
        )

    @app.exception_handler(RequestBodyTooLargeError)
    async def _too_large(_: Request, __: RequestBodyTooLargeError) -> JSONResponse:
        return JSONResponse(
            error_payload("REQUEST_TOO_LARGE", "The request body is too large."), status_code=413
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            error_payload(code, message), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error", exc_info=exc)
        return JSONResponse(
            error_payload("INTERNAL_ERROR", "An unexpected error occurred."), status_code=500
        )
