"""Application errors rendered as the doc-05 §7 error envelope.

Services raise these; the API layer converts them to JSON. Messages are user-safe: never put
provider secrets, raw payloads or stack traces in them.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class InvalidRequestError(AppError):
    code = "INVALID_REQUEST"
    http_status = 400
    message = "The request is invalid."


class SemanticValidationError(AppError):
    code = "UNPROCESSABLE_REQUEST"
    http_status = 422
    message = "The request is well-formed but cannot be processed."


class UnauthenticatedError(AppError):
    code = "UNAUTHENTICATED"
    http_status = 401
    message = "Authentication is required."


class ConflictError(AppError):
    code = "CONFLICT"
    http_status = 409
    message = "The request conflicts with the current state."


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404
    message = "The requested resource was not found."


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    http_status = 429
    message = "Too many requests. Please wait before trying again."


class ProviderUnavailableError(AppError):
    code = "PROVIDER_UNAVAILABLE"
    http_status = 503
    message = "The railway data provider is currently unavailable."


class ProviderTimeoutError(AppError):
    code = "PROVIDER_TIMEOUT"
    http_status = 504
    message = "The railway data provider did not respond in time."


class ProviderBadResponseError(AppError):
    code = "PROVIDER_BAD_RESPONSE"
    http_status = 502
    message = "The railway data provider returned an invalid response."


class ServiceUnavailableError(AppError):
    code = "SERVICE_UNAVAILABLE"
    http_status = 503
    message = "The service is temporarily unavailable."


def require[T](value: T | None, what: str) -> T:
    """Narrow an Optional that an earlier step guarantees; violations are programming errors."""
    if value is None:
        raise RuntimeError(f"invariant violated: {what} is missing")
    return value
