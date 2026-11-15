"""Provider-neutral error taxonomy. Provider adapters translate their failures into these."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.domain.enums import SegmentQueryOutcome


class ProviderErrorCategory(StrEnum):
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH = "AUTH"
    NOT_FOUND = "NOT_FOUND"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UPSTREAM = "UPSTREAM"
    REJECTED = "REJECTED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"


OUTCOME_BY_CATEGORY: dict[ProviderErrorCategory, SegmentQueryOutcome] = {
    ProviderErrorCategory.TIMEOUT: SegmentQueryOutcome.PROVIDER_TIMEOUT,
    ProviderErrorCategory.RATE_LIMITED: SegmentQueryOutcome.RATE_LIMITED,
    ProviderErrorCategory.AUTH: SegmentQueryOutcome.AUTH_ERROR,
    ProviderErrorCategory.NOT_FOUND: SegmentQueryOutcome.NOT_FOUND,
    ProviderErrorCategory.INVALID_RESPONSE: SegmentQueryOutcome.INVALID_RESPONSE,
    ProviderErrorCategory.UPSTREAM: SegmentQueryOutcome.UPSTREAM_ERROR,
    ProviderErrorCategory.REJECTED: SegmentQueryOutcome.PROVIDER_REJECTED,
    ProviderErrorCategory.QUOTA_EXHAUSTED: SegmentQueryOutcome.QUOTA_EXHAUSTED,
}


class ProviderError(Exception):
    """Base provider failure. ``message`` must be safe to log (no secrets, bounded length)."""

    category: ProviderErrorCategory = ProviderErrorCategory.UPSTREAM

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        endpoint: str,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message[:300]
        self.provider = provider
        self.endpoint = endpoint
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        #: Sanitized context (e.g. offending payload excerpt) for logs and fixtures.
        self.diagnostics = diagnostics or {}

    @property
    def outcome(self) -> SegmentQueryOutcome:
        return OUTCOME_BY_CATEGORY[self.category]

    @property
    def retryable(self) -> bool:
        return self.category in {ProviderErrorCategory.TIMEOUT, ProviderErrorCategory.UPSTREAM}


class ProviderTimeoutError(ProviderError):
    category = ProviderErrorCategory.TIMEOUT


class ProviderRateLimitedError(ProviderError):
    category = ProviderErrorCategory.RATE_LIMITED


class ProviderAuthError(ProviderError):
    category = ProviderErrorCategory.AUTH


class ProviderNotFoundError(ProviderError):
    category = ProviderErrorCategory.NOT_FOUND


class ProviderInvalidResponseError(ProviderError):
    category = ProviderErrorCategory.INVALID_RESPONSE


class ProviderUpstreamError(ProviderError):
    category = ProviderErrorCategory.UPSTREAM


class ProviderRejectedError(ProviderError):
    """The provider refused the request as invalid (HTTP 400), e.g. an unsupported stop pair."""

    category = ProviderErrorCategory.REJECTED


class ProviderQuotaExhaustedError(ProviderError):
    """Our own quota guard refused the call before it reached the provider."""

    category = ProviderErrorCategory.QUOTA_EXHAUSTED
