from __future__ import annotations

from datetime import date

import pytest

from app.domain.enums import AvailabilityStatus as S
from app.domain.enums import Quota
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


# --- Quotas ---------------------------------------------------------------------------------------
def qq(train: str, src: str, dst: str, quota: Quota, cls: str = "3A") -> AvailabilityQuery:
    return AvailabilityQuery(train, src, dst, DAY, cls, quota)


async def test_each_quota_is_answered_separately_and_echoed() -> None:
    provider = MockRailwayProvider()
    assert provider.supported_quotas == frozenset(Quota)
    answers = {
        quota: await provider.get_availability(qq("90601", "TIR", "TVC", quota)) for quota in Quota
    }
    assert answers[Quota.GENERAL].raw_status == "GNWL42/WL27"  # demo override (General only)
    assert answers[Quota.TATKAL].raw_status != answers[Quota.GENERAL].raw_status
    for quota, record in answers.items():
        assert record.raw_payload is not None
        assert record.raw_payload["quota"] == quota.value
    general, tatkal = answers[Quota.GENERAL].fare, answers[Quota.TATKAL].fare
    assert general is not None
    assert tatkal is not None
    assert tatkal.amount > general.amount  # simulated Tatkal premium


async def test_tatkal_waitlists_are_tatkal_waitlists() -> None:
    provider = MockRailwayProvider(overrides={})
    route = [s.code for s in demo_trains()["90601"].stops]
    seen: set[S] = set()
    for i in range(len(route) - 1):
        for j in range(i + 1, len(route)):
            record = await provider.get_availability(qq("90601", route[i], route[j], Quota.TATKAL))
            seen.add(record.status)
            if record.status is S.WAITLIST:
                assert record.waitlist_type == "TQWL"
    assert S.WAITLIST in seen


async def test_unsupported_quota_is_rejected_like_railkit() -> None:
    provider = MockRailwayProvider(quotas=(Quota.GENERAL,))
    with pytest.raises(ProviderRejectedError, match="Quota not allowed"):
        await provider.get_availability(qq("90601", "TIR", "TVC", Quota.TATKAL))


async def test_quota_specific_overrides_and_failures() -> None:
    provider = MockRailwayProvider(
        overrides={
            ("90601", "TIR", "ERS", "3A", "TQ"): ("TQWL3/WL2", "70% Chance", 70),
            ("90601", "TIR", "ERS", "3A"): ("AVAILABLE-0007", None, None),
        },
        failures={
            ("90601", "ERS", "TVC", "3A", "TQ"): ProviderTimeoutError(
                "x", provider="MOCK", endpoint="seat_availability"
            )
        },
    )
    record = await provider.get_availability(qq("90601", "TIR", "ERS", Quota.TATKAL))
    assert (record.status, record.waitlist_type) == (S.WAITLIST, "TQWL")
    general = await provider.get_availability(qq("90601", "TIR", "ERS", Quota.GENERAL))
    assert general.raw_status == "AVAILABLE-0007"  # the General override is untouched
    with pytest.raises(ProviderTimeoutError):
        await provider.get_availability(qq("90601", "ERS", "TVC", Quota.TATKAL))
    assert (await provider.get_availability(qq("90601", "ERS", "TVC", Quota.GENERAL))).status
