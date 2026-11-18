"""Low-level RailKit HTTP client (doc 07 §6).

* One shared ``httpx.AsyncClient`` (connection pooling), closed on shutdown.
* ``x-api-key`` is attached per request and never logged or echoed.
* Bounded retries with jittered exponential backoff for timeouts, network errors and 5xx only.
  400/401/403/404/429 are never retried. Every attempt passes the quota observer first, is
  reported to the caller's per-call gate, and every retry needs the gate's permission (a search
  budget pays for retries; docs/08 D-28). A call the caller withdrew (search stopped, D-35) is
  never sent: checked before the quota guard and again after waiting for a connection slot.
* A semaphore bounds concurrent in-flight requests for the whole process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.core.redaction import sanitize_payload
from app.providers.base import (
    NullRequestObserver,
    ProviderRequestEvent,
    ProviderRequestObserver,
    ensure_may_start,
    report_attempt,
    retry_allowed,
)
from app.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "RAILKIT"
USER_AGENT = "RailRouteOptimizer/0.1 (server)"
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
_MAX_ERROR_TEXT = 200

Sleep = Callable[[float], Awaitable[None]]


def path_segment(value: str) -> str:
    """URL-encode one path segment (values are validated upstream; this is defence in depth)."""
    return quote(value, safe="")


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, retry_at.timestamp() - time.time())


def _error_text(payload: Any) -> str:
    if isinstance(payload, Mapping):
        error = payload.get("error") or payload.get("message")
        if isinstance(error, str):
            return error[:_MAX_ERROR_TEXT]
    return ""


class RailKitHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: httpx.Timeout,
        max_retries: int = 1,
        backoff_seconds: float = 0.5,
        max_concurrency: int = 4,
        observer: ProviderRequestObserver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("RailKit API key is required")
        self._api_key = api_key
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._observer: ProviderRequestObserver = observer or NullRequestObserver()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"accept": "application/json", "user-agent": USER_AGENT},
            limits=httpx.Limits(
                max_connections=max_concurrency * 2, max_keepalive_connections=max_concurrency
            ),
            follow_redirects=False,
        )

    def set_observer(self, observer: ProviderRequestObserver) -> None:
        self._observer = observer

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_data(
        self, endpoint: str, path: str, params: Mapping[str, str] | None = None
    ) -> Any:
        """GET ``path`` and return the ``data`` member of RailKit's success envelope."""
        attempt = 0
        while True:
            attempt += 1
            ensure_may_start()  # withdrawn (search stopped): not sent, not counted by the guard
            await self._observer.before_request(PROVIDER_NAME, endpoint)
            started = time.perf_counter()
            status_code: int | None = None
            try:
                async with self._semaphore:
                    # It may have been withdrawn while waiting for a free connection slot.
                    ensure_may_start()
                    report_attempt()
                    response = await self._client.get(
                        path, params=params, headers={"x-api-key": self._api_key}
                    )
                status_code = response.status_code
                data = self._interpret(endpoint, response)
            except ProviderError as error:
                await self._record(
                    endpoint, attempt, error.category.value, status_code, started, error
                )
                if error.retryable and await self._may_retry(attempt):
                    await self._backoff_sleep(attempt)
                    continue
                raise
            except httpx.TimeoutException as exc:
                timeout_error = ProviderTimeoutError(
                    f"RailKit request timed out ({type(exc).__name__})",
                    provider=PROVIDER_NAME,
                    endpoint=endpoint,
                )
                await self._record(endpoint, attempt, "TIMEOUT", None, started, timeout_error)
                if await self._may_retry(attempt):
                    await self._backoff_sleep(attempt)
                    continue
                raise timeout_error from None
            except httpx.TransportError as exc:
                network_error = ProviderUpstreamError(
                    f"RailKit network error ({type(exc).__name__})",
                    provider=PROVIDER_NAME,
                    endpoint=endpoint,
                )
                await self._record(endpoint, attempt, "UPSTREAM", None, started, network_error)
                if await self._may_retry(attempt):
                    await self._backoff_sleep(attempt)
                    continue
                raise network_error from None
            else:
                await self._record(endpoint, attempt, "SUCCESS", status_code, started, None)
                return data

    async def _may_retry(self, attempt: int) -> bool:
        """Within the retry limit *and* allowed by the caller's per-call budget (D-28)."""
        return attempt <= self._max_retries and await retry_allowed()

    async def _backoff_sleep(self, attempt: int) -> None:
        delay = self._backoff * (2 ** (attempt - 1))
        await self._sleep(delay * random.uniform(0.8, 1.2))  # noqa: S311 (jitter, not crypto)

    async def _record(
        self,
        endpoint: str,
        attempt: int,
        outcome: str,
        status_code: int | None,
        started: float,
        error: ProviderError | None,
    ) -> None:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        event = ProviderRequestEvent(
            provider=PROVIDER_NAME,
            endpoint=endpoint,
            attempt=attempt,
            outcome=outcome,
            status_code=status_code,
            latency_ms=latency_ms,
            retry_after_seconds=error.retry_after_seconds if error else None,
        )
        log = logger.info if error is None else logger.warning
        log(
            "provider request",
            extra={
                "provider": PROVIDER_NAME,
                "endpoint": endpoint,
                "attempt": attempt,
                "outcome": outcome,
                "status_code": status_code,
                "latency_ms": latency_ms,
                **({"error": error.message} if error else {}),
            },
        )
        await self._observer.after_request(event)

    def _interpret(self, endpoint: str, response: httpx.Response) -> Any:
        status = response.status_code
        try:
            payload: Any = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            payload = None
        message = _error_text(payload)
        common: dict[str, Any] = {
            "provider": PROVIDER_NAME,
            "endpoint": endpoint,
            "status_code": status,
        }

        if status in (401, 403):
            raise ProviderAuthError(message or "RailKit rejected the API key", **common)
        if status == 404:
            raise ProviderNotFoundError(message or "RailKit record not found", **common)
        if status == 429:
            raise ProviderRateLimitedError(
                message or "RailKit usage limit exceeded",
                retry_after_seconds=_parse_retry_after(response.headers.get("retry-after")),
                **common,
            )
        if status == 400:
            raise ProviderRejectedError(message or "RailKit rejected the request", **common)
        if status in _RETRYABLE_STATUS or status >= 500:
            raise ProviderUpstreamError(message or f"RailKit server error {status}", **common)
        if not 200 <= status < 300:
            raise ProviderUpstreamError(message or f"Unexpected RailKit status {status}", **common)

        if not isinstance(payload, Mapping):
            raise ProviderInvalidResponseError(
                "RailKit response is not a JSON object",
                diagnostics={"body_excerpt": response.text[:300]},
                **common,
            )
        success = payload.get("success")
        if success is False:
            raise ProviderUpstreamError(message or "RailKit reported failure", **common)
        if success is not True:
            raise ProviderInvalidResponseError(
                "RailKit envelope lacks success=true",
                diagnostics={"payload": sanitize_payload(payload, max_items=20)},
                **common,
            )
        if "data" not in payload:
            raise ProviderInvalidResponseError("RailKit envelope lacks data", **common)
        return payload["data"]
