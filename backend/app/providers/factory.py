"""Selects the provider implementation. The only module allowed to import RailKit code."""

from __future__ import annotations

import httpx

from app.core.clock import Clock
from app.core.config import ProviderName, Settings
from app.domain.enums import Quota
from app.integrations.railkit.client import RailKitHttpClient
from app.integrations.railkit.provider import RailKitProvider
from app.providers.base import ProviderRequestObserver, RailwayProvider
from app.providers.mock.provider import MockRailwayProvider


def build_provider(
    settings: Settings,
    *,
    clock: Clock,
    observer: ProviderRequestObserver,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RailwayProvider:
    if settings.railway_provider is ProviderName.MOCK:
        return MockRailwayProvider(latency_ms=settings.mock_latency_ms)

    if settings.railkit_api_key is None:  # Settings validation already guarantees this
        raise ValueError("RAILKIT_API_KEY is required for the RailKit provider")
    client = RailKitHttpClient(
        base_url=settings.railkit_base_url,
        api_key=settings.railkit_api_key.get_secret_value(),
        timeout=httpx.Timeout(
            connect=settings.railkit_connect_timeout_seconds,
            read=settings.railkit_read_timeout_seconds,
            write=settings.railkit_write_timeout_seconds,
            pool=settings.railkit_pool_timeout_seconds,
        ),
        max_retries=settings.railkit_max_retries,
        backoff_seconds=settings.railkit_retry_backoff_seconds,
        max_concurrency=settings.railkit_max_concurrency,
        observer=observer,
        transport=transport,
    )
    return RailKitProvider(
        client,
        clock=clock,
        fare_currency=settings.railkit_fare_currency,
        secret_fragments=settings.secret_values,
        supported_quotas=[Quota(code) for code in settings.railkit_supported_quotas],
    )
