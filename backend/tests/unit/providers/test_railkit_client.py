from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime

import httpx
import pytest

from app.core.clock import FrozenClock
from app.domain.enums import Quota
from app.domain.models import AvailabilityQuery
from app.integrations.railkit.client import RailKitHttpClient
from app.integrations.railkit.provider import RailKitProvider
from app.providers.base import ProviderRequestEvent, call_gate
from app.providers.errors import (
    ProviderAuthError,
    ProviderInvalidResponseError,
    ProviderNotFoundError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from tests.unit.providers.railkit_helpers import Router, json_response, load_fixture

API_KEY = "rk_test_key_0123456789"


class RecordingObserver:
    def __init__(self, *, block_after: int | None = None) -> None:
        self.events: list[ProviderRequestEvent] = []
        self.before_calls = 0
        self.block_after = block_after

    async def before_request(self, provider: str, endpoint: str) -> None:
        self.before_calls += 1
        if self.block_after is not None and self.before_calls > self.block_after:
            raise ProviderQuotaExhaustedError("quota guard", provider=provider, endpoint=endpoint)

    async def after_request(self, event: ProviderRequestEvent) -> None:
        self.events.append(event)


async def _no_sleep(_: float) -> None:
    return None


def make_client(
    router: Router, observer: RecordingObserver | None = None, retries: int = 1
) -> RailKitHttpClient:
    return RailKitHttpClient(
        base_url="https://api.railkit.test",
        api_key=API_KEY,
        timeout=httpx.Timeout(1.0),
        max_retries=retries,
        backoff_seconds=0.0,
        observer=observer,
        transport=router.transport,
        sleep=_no_sleep,
    )


async def test_success_unwraps_data_and_sends_api_key_header() -> None:
    router = Router(json_response(200, {"success": True, "data": [1, 2]}))
    client = make_client(router)
    assert await client.get_data("x", "/api/v1/x") == [1, 2]
    request = router.requests[0]
    assert request.headers["x-api-key"] == API_KEY
    assert request.headers["accept"] == "application/json"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (404, ProviderNotFoundError),
        (400, ProviderRejectedError),
        (429, ProviderRateLimitedError),
    ],
)
async def test_client_errors_are_not_retried(status: int, error: type[Exception]) -> None:
    router = Router(json_response(status, {"success": False, "error": "nope"}))
    observer = RecordingObserver()
    with pytest.raises(error):
        await make_client(router, observer, retries=3).get_data("x", "/x")
    assert len(router.requests) == 1
    assert len(observer.events) == 1


async def test_429_exposes_retry_after() -> None:
    router = Router(
        json_response(
            429, {"success": False, "error": "Usage limit exceeded"}, {"Retry-After": "120"}
        )
    )
    with pytest.raises(ProviderRateLimitedError) as info:
        await make_client(router).get_data("x", "/x")
    assert info.value.retry_after_seconds == 120.0
    assert info.value.message == "Usage limit exceeded"


async def test_5xx_is_retried_then_succeeds_and_every_attempt_is_counted() -> None:
    router = Router(
        json_response(503, {"success": False, "error": "busy"}),
        json_response(200, {"success": True, "data": {"ok": 1}}),
    )
    observer = RecordingObserver()
    assert await make_client(router, observer).get_data("x", "/x") == {"ok": 1}
    assert len(router.requests) == 2
    assert [e.outcome for e in observer.events] == ["UPSTREAM", "SUCCESS"]
    assert observer.before_calls == 2  # quota guard consulted per attempt


async def test_5xx_retries_are_bounded() -> None:
    router = Router(json_response(500, {"success": False, "error": "Internal server error"}))
    with pytest.raises(ProviderUpstreamError):
        await make_client(router, retries=2).get_data("x", "/x")
    assert len(router.requests) == 3


async def test_timeout_is_retried_then_raised() -> None:
    router = Router(httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeoutError):
        await make_client(router, retries=1).get_data("x", "/x")
    assert len(router.requests) == 2


async def test_network_error_maps_to_upstream() -> None:
    router = Router(httpx.ConnectError("refused"))
    with pytest.raises(ProviderUpstreamError):
        await make_client(router, retries=0).get_data("x", "/x")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>oops</html>"),
        json_response(200, ["not", "an", "object"]),
        json_response(200, {"data": {}}),
        json_response(200, {"success": True}),
    ],
)
async def test_malformed_envelopes_are_invalid_response(response: httpx.Response) -> None:
    with pytest.raises(ProviderInvalidResponseError):
        await make_client(Router(response), retries=3).get_data("x", "/x")


async def test_success_false_with_200_is_upstream_error() -> None:
    router = Router(json_response(200, {"success": False, "error": "upstream rejected"}))
    with pytest.raises(ProviderUpstreamError, match="upstream rejected"):
        await make_client(router).get_data("x", "/x")


async def test_quota_guard_blocks_before_any_http_call() -> None:
    router = Router(json_response(200, {"success": True, "data": 1}))
    with pytest.raises(ProviderQuotaExhaustedError):
        await make_client(router, RecordingObserver(block_after=0)).get_data("x", "/x")
    assert router.requests == []


async def test_quota_guard_also_blocks_retries() -> None:
    router = Router(json_response(503, {"success": False, "error": "busy"}))
    with pytest.raises(ProviderQuotaExhaustedError):
        await make_client(router, RecordingObserver(block_after=1), retries=3).get_data("x", "/x")
    assert len(router.requests) == 1


class Gate:
    """A per-call gate (D-28) that allows ``retries`` retries and records every attempt."""

    def __init__(self, retries: int) -> None:
        self.retries = retries
        self.attempts = 0
        self.asked = 0

    def attempt_started(self) -> None:
        self.attempts += 1

    async def allow_retry(self) -> bool:
        self.asked += 1
        if self.retries <= 0:
            return False
        self.retries -= 1
        return True


async def test_every_attempt_is_reported_to_the_call_gate() -> None:
    router = Router(
        json_response(503, {"success": False, "error": "busy"}),
        json_response(200, {"success": True, "data": {"ok": 1}}),
    )
    gate = Gate(retries=1)
    with call_gate(gate):
        assert await make_client(router, retries=3).get_data("x", "/x") == {"ok": 1}
    assert (gate.attempts, gate.asked, len(router.requests)) == (2, 1, 2)


async def test_a_refused_retry_ends_the_call_with_its_real_error() -> None:
    router = Router(json_response(503, {"success": False, "error": "busy"}))
    observer = RecordingObserver()
    gate = Gate(retries=0)
    with call_gate(gate), pytest.raises(ProviderUpstreamError, match="busy"):
        await make_client(router, observer, retries=3).get_data("x", "/x")
    assert (gate.attempts, gate.asked, len(router.requests), observer.before_calls) == (1, 1, 1, 1)


async def test_non_retryable_errors_never_ask_the_gate() -> None:
    router = Router(json_response(400, {"success": False, "error": "bad"}))
    gate = Gate(retries=5)
    with call_gate(gate), pytest.raises(ProviderRejectedError):
        await make_client(router, retries=3).get_data("x", "/x")
    assert (gate.attempts, gate.asked) == (1, 0)


async def test_guard_refusal_is_not_reported_as_an_attempt() -> None:
    router = Router(json_response(200, {"success": True, "data": 1}))
    gate = Gate(retries=5)
    with call_gate(gate), pytest.raises(ProviderQuotaExhaustedError):
        await make_client(router, RecordingObserver(block_after=0)).get_data("x", "/x")
    assert gate.attempts == 0


async def test_api_key_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    router = Router(json_response(401, {"success": False, "error": "Invalid API key"}))
    with pytest.raises(ProviderAuthError) as info:
        await make_client(router).get_data("x", "/x")
    assert API_KEY not in caplog.text
    assert API_KEY not in str(info.value)


async def test_concurrency_is_bounded() -> None:
    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return json_response(200, {"success": True, "data": 1})

    client = RailKitHttpClient(
        base_url="https://api.railkit.test",
        api_key=API_KEY,
        timeout=httpx.Timeout(1.0),
        max_concurrency=2,
        transport=httpx.MockTransport(handler),
    )
    await asyncio.gather(*(client.get_data("x", "/x") for _ in range(8)))
    assert peak == 2


# --- Provider: URL construction for every endpoint ------------------------------------------------
async def test_provider_builds_documented_urls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/api/v1/seats/"):
            return json_response(200, load_fixture("seat_availability_docs.json"))
        if path.startswith("/api/v1/trains/between/"):
            return json_response(200, load_fixture("train_search_docs.json"))
        if path.endswith("/info"):
            return json_response(200, load_fixture("train_info_docs.json"))
        return json_response(200, load_fixture("station_search_docs.json"))

    router = Router(handler)
    provider = RailKitProvider(
        make_client(router),
        clock=FrozenClock(datetime(2026, 11, 8, tzinfo=UTC)),
        fare_currency="INR",
    )
    await provider.search_stations("delhi")
    await provider.search_trains("NZM", "BDTS", date(2026, 9, 1))
    await provider.get_train_route("12345")
    await provider.get_availability(
        AvailabilityQuery("12904", "NZM", "BDTS", date(2026, 9, 1), "3A")
    )

    urls = [str(r.url) for r in router.requests]
    assert urls == [
        "https://api.railkit.test/api/v1/stations/search?name=delhi",
        "https://api.railkit.test/api/v1/trains/between/NZM/BDTS?date=01-09-2026",
        "https://api.railkit.test/api/v1/trains/12345/info",
        "https://api.railkit.test/api/v1/seats/12904/NZM/BDTS/01-09-2026/3A/GN",
    ]
    assert provider.is_live
    assert provider.name == "RAILKIT"


async def test_station_lookup_by_code_url_and_not_found() -> None:
    payload = {
        "success": True,
        "data": {"code": "TVCN", "name": "THIRUVANANTHAPURAM NORTH", "lat": None, "lon": None},
    }
    router = Router(
        json_response(200, payload),
        json_response(404, {"success": False, "error": "Station not found"}),
    )
    provider = RailKitProvider(
        make_client(router),
        clock=FrozenClock(datetime(2026, 11, 8, tzinfo=UTC)),
        fare_currency="INR",
    )
    found = await provider.get_station("tvcn")
    assert found is not None
    assert found.code == "TVCN"
    assert await provider.get_station("ZZZZ") is None
    assert [r.url.path for r in router.requests] == [
        "/api/v1/stations/TVCN",
        "/api/v1/stations/ZZZZ",
    ]


async def test_tatkal_quota_is_sent_in_the_path() -> None:
    payload = load_fixture("seat_availability_docs.json")
    payload["data"]["train"]["quota"] = "TQ"
    router = Router(json_response(200, payload))
    provider = RailKitProvider(
        make_client(router),
        clock=FrozenClock(datetime(2026, 11, 8, tzinfo=UTC)),
        fare_currency="INR",
    )
    assert provider.supported_quotas == frozenset({Quota.GENERAL, Quota.TATKAL})
    record = await provider.get_availability(
        AvailabilityQuery("12904", "NZM", "BDTS", date(2026, 9, 1), "3A", Quota.TATKAL)
    )
    assert record.anomalies == ()
    assert [r.url.path for r in router.requests] == [
        "/api/v1/seats/12904/NZM/BDTS/01-09-2026/3A/TQ"
    ]


async def test_disabling_tatkal_by_configuration_sends_no_request() -> None:
    router = Router(json_response(200, load_fixture("seat_availability_docs.json")))
    provider = RailKitProvider(
        make_client(router),
        clock=FrozenClock(datetime(2026, 11, 8, tzinfo=UTC)),
        fare_currency="INR",
        supported_quotas=[Quota.GENERAL],
    )
    with pytest.raises(ProviderRejectedError, match="not supported"):
        await provider.get_availability(
            AvailabilityQuery("12904", "NZM", "BDTS", date(2026, 9, 1), "3A", Quota.TATKAL)
        )
    assert router.requests == []
