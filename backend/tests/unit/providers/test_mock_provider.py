from __future__ import annotations

from datetime import date

import pytest

from app.domain.enums import AvailabilityStatus as S
from app.domain.models import AvailabilityQuery
from app.providers.base import RailwayProvider
from app.providers.errors import ProviderNotFoundError, ProviderRejectedError, ProviderTimeoutError
from app.providers.mock.dataset import demo_trains
from app.providers.mock.provider import MockRailwayProvider

DAY = date(2026, 11, 20)


def q(train: str, src: str, dst: str, cls: str = "3A", day: date = DAY) -> AvailabilityQuery:
    return AvailabilityQuery(train, src, dst, day, cls)


def test_mock_satisfies_provider_protocol_and_is_labelled_demo() -> None:
    provider = MockRailwayProvider()
    assert isinstance(provider, RailwayProvider)
    assert provider.is_live is False
    assert provider.name == "MOCK"


async def test_availability_is_deterministic() -> None:
    a, b = MockRailwayProvider(), MockRailwayProvider()
    for query in (q("90601", "TCR", "KTYM"), q("90603", "SRR", "QLN", "SL")):
        first, second = await a.get_availability(query), await b.get_availability(query)
        assert (first.status, first.raw_status) == (second.status, second.raw_status)


async def test_showcase_direct_ticket_is_waitlisted_but_split_is_available() -> None:
    provider = MockRailwayProvider()
    direct = await provider.get_availability(q("90601", "TIR", "TVC"))
    assert direct.status is S.WAITLIST
    assert direct.prediction is not None
    assert direct.prediction.percentage == 38.0
    first = await provider.get_availability(q("90601", "TIR", "ERS"))
    second = await provider.get_availability(q("90601", "ERS", "TVC"))
    assert first.status is S.AVAILABLE
    assert second.status is S.AVAILABLE


async def test_train_search_finds_both_showcase_trains_in_departure_order() -> None:
    trains = await MockRailwayProvider().search_trains("TIR", "TVC", DAY)
    assert [t.train_number for t in trains] == ["90601", "90603"]
    assert all(t.from_station_code == "TIR" for t in trains)


async def test_route_crosses_midnight_with_day_offsets() -> None:
    route = await MockRailwayProvider().get_train_route("90601")
    offsets = [s.day_offset if s.day_offset is not None else -1 for s in route.stops]
    assert offsets[0] == 0
    assert offsets[-1] == 1
    assert offsets == sorted(offsets)
    assert route.classes == ("2A", "3A", "SL")


def test_generated_timetables_are_monotonic() -> None:
    for train in demo_trains().values():
        absolute = []
        for stop in train.stops:
            clock = stop.arrival or stop.departure
            assert clock is not None
            absolute.append((stop.day - 1) * 1440 + clock.hour * 60 + clock.minute)
        assert absolute == sorted(absolute), train.number


async def test_unknown_train_and_bad_pairs_are_errors_not_unavailable() -> None:
    provider = MockRailwayProvider()
    with pytest.raises(ProviderNotFoundError):
        await provider.get_train_route("99999")
    with pytest.raises(ProviderRejectedError):
        await provider.get_availability(q("90601", "TVC", "TIR"))
    with pytest.raises(ProviderRejectedError):
        await provider.get_availability(q("90601", "TIR", "TVC", "1A"))


async def test_failure_injection_and_call_counting() -> None:
    failure = ProviderTimeoutError("slow", provider="MOCK", endpoint="seat_availability")
    provider = MockRailwayProvider(failures={("90601", "TIR", "SRR", "3A"): failure})
    with pytest.raises(ProviderTimeoutError):
        await provider.get_availability(q("90601", "TIR", "SRR"))
    assert provider.calls["seat_availability"] == 1
    assert provider.availability_queries[0].from_station == "TIR"


async def test_station_search_prefers_exact_code_then_prefix() -> None:
    results = await MockRailwayProvider().search_stations("tir")
    assert results[0].code == "TIR"
    assert all("tir" in s.name.lower() or s.code.startswith("TIR") for s in results)
