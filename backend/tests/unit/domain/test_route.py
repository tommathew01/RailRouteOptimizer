from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from app.domain.enums import AvailabilityDatePolicy as Policy
from app.domain.models import TrainRoute, TrainStop
from app.domain.route import (
    RouteIssue,
    analyze_route,
    boards_on_other_calendar_day,
    departure_day,
    provider_query_date,
    scheduled_arrival,
    scheduled_departure,
    train_start_date,
    validate_journey,
)
from app.domain.time import IST
from app.integrations.railkit.mapper import map_train_route
from tests.unit.providers.railkit_helpers import load_fixture

NOW = datetime(2026, 11, 8, tzinfo=UTC)


def stop(
    seq: int, code: str, arr: str | None, dep: str | None, day: int | None, **kw: object
) -> TrainStop:
    def t(v: str | None) -> time | None:
        return None if v is None else time.fromisoformat(v)

    return TrainStop(seq, code, code.title(), t(arr), t(dep), day, **kw)  # type: ignore[arg-type]


def route(*stops: TrainStop) -> TrainRoute:
    return TrainRoute("16999", "TEST", tuple(stops), "TEST", NOW)


OVERNIGHT = route(
    stop(0, "CLT", None, "22:30", 0),
    stop(1, "TIR", "23:21", "23:23", 0),
    stop(2, "SRR", "23:58", "00:08", 0),  # midnight during the halt
    stop(3, "TCR", "00:50", "00:53", 1),
    stop(4, "ERS", "02:20", "02:30", 1),
    stop(5, "TVC", "06:05", None, 1),
)


def test_overnight_route_is_verified_and_departure_days_follow_clock() -> None:
    analysis = analyze_route(OVERNIGHT)
    assert analysis.verified
    assert analysis.issues == ()
    assert [departure_day(analysis, i) for i in range(5)] == [0, 0, 1, 1, 1]


def test_mapped_synthetic_fixture_matches_hand_built_route() -> None:
    data = load_fixture("train_info_synthetic_overnight.json")["data"]
    analysis = analyze_route(map_train_route(data, train_number="16999", fetched_at=NOW))
    assert analysis.verified
    assert departure_day(analysis, 2) == 1  # SRR leaves at 00:08 on day 2


@pytest.mark.parametrize(
    ("stops", "issue"),
    [
        ((stop(0, "CLT", None, "22:30", 0),), RouteIssue.EMPTY_ROUTE),
        (
            (stop(0, "CLT", None, "22:30", 0), stop(1, "bad!", "23:00", None, 0)),
            RouteIssue.INVALID_STATION_CODE,
        ),
        (
            (stop(0, "CLT", None, "22:30", 0), stop(1, "TIR", "23:00", None, None)),
            RouteIssue.MISSING_DAY_OFFSET,
        ),
        (
            (stop(0, "CLT", None, "22:30", 1), stop(1, "TIR", "23:00", None, 0)),
            RouteIssue.DAY_OFFSET_DECREASING,
        ),
        (
            (stop(0, "CLT", None, "22:30", 0), stop(1, "TIR", "23:00", None, 2)),
            RouteIssue.DAY_OFFSET_GAP,
        ),
        # clock goes backwards without the day advancing -> order or day data cannot be trusted
        (
            (stop(0, "CLT", None, "22:30", 0), stop(1, "TIR", "01:00", None, 0)),
            RouteIssue.TIME_ORDER_INCONSISTENT,
        ),
    ],
)
def test_untrustworthy_routes_are_unverified(
    stops: tuple[TrainStop, ...], issue: RouteIssue
) -> None:
    analysis = analyze_route(route(*stops))
    assert issue in analysis.issues
    assert not analysis.verified


def test_duplicate_and_timeless_stops_are_excluded_but_route_stays_usable() -> None:
    analysis = analyze_route(
        route(
            stop(0, "AAA", None, "10:00", 0),
            stop(1, "BBB", "10:30", "10:32", 0),
            stop(2, "CCC", None, None, 0),
            stop(3, "BBB", "11:30", "11:32", 0),
            stop(4, "DDD", "12:00", None, 0),
        )
    )
    assert analysis.verified
    assert {RouteIssue.DUPLICATE_STATION, RouteIssue.STOP_TIME_MISSING} <= set(analysis.issues)
    journey = validate_journey(analysis, "AAA", "DDD")
    assert journey.verified
    assert journey.boundary_indices == (0, 4)  # BBB (twice) and CCC excluded as boundaries


def test_non_stoppage_points_are_not_boundaries() -> None:
    analysis = analyze_route(
        route(
            stop(0, "AAA", None, "10:00", 0),
            stop(1, "BBB", "10:30", "10:30", 0, is_stoppage=False),
            stop(2, "CCC", "11:00", None, 0),
        )
    )
    assert validate_journey(analysis, "AAA", "CCC").boundary_indices == (0, 2)


@pytest.mark.parametrize(
    ("source", "destination", "issue"),
    [
        ("XXX", "TVC", RouteIssue.SOURCE_NOT_ON_ROUTE),
        ("CLT", "XXX", RouteIssue.DESTINATION_NOT_ON_ROUTE),
        ("TVC", "CLT", RouteIssue.SOURCE_AFTER_DESTINATION),
        ("TIR", "TIR", RouteIssue.SAME_SOURCE_AND_DESTINATION),
    ],
)
def test_journey_validation_failures(source: str, destination: str, issue: RouteIssue) -> None:
    journey = validate_journey(analyze_route(OVERNIGHT), source, destination)
    assert issue in journey.issues
    assert not journey.verified
    assert journey.boundary_indices == ()


def test_ambiguous_source_is_rejected() -> None:
    analysis = analyze_route(
        route(
            stop(0, "AAA", None, "10:00", 0),
            stop(1, "BBB", "10:30", "10:32", 0),
            stop(2, "AAA", "11:00", "11:02", 0),
            stop(3, "CCC", "12:00", None, 0),
        )
    )
    journey = validate_journey(analysis, "AAA", "CCC")
    assert RouteIssue.SOURCE_AMBIGUOUS in journey.issues
    assert not journey.verified


def test_valid_journey_boundaries_are_the_requested_interval_only() -> None:
    journey = validate_journey(analyze_route(OVERNIGHT), "TIR", "ERS")
    assert journey.verified
    assert (journey.source_index, journey.destination_index) == (1, 4)
    assert journey.boundary_indices == (1, 2, 3, 4)
    assert journey.intermediate_indices == (2, 3)


def test_unverified_route_never_yields_a_journey() -> None:
    broken = route(
        stop(0, "CLT", None, "22:30", 0),
        stop(1, "TIR", "01:00", "01:02", 0),
        stop(2, "TVC", "03:00", None, 0),
    )
    assert not validate_journey(analyze_route(broken), "CLT", "TVC").verified


def test_date_policies_for_segments_boarding_after_midnight() -> None:
    analysis = analyze_route(OVERNIGHT)
    journey_date = date(2026, 11, 20)  # passenger departs TIR on 20 Nov (23:23)
    start = train_start_date(journey_date, analysis, source_index=1)
    assert start == date(2026, 11, 20)
    # SRR departs at 00:08 on the next calendar day
    assert provider_query_date(start, analysis, 2, Policy.SEGMENT_BOARDING_DATE) == date(
        2026, 11, 21
    )
    assert provider_query_date(start, analysis, 2, Policy.TRAIN_START_DATE) == date(2026, 11, 20)
    assert provider_query_date(start, analysis, 1, Policy.SEGMENT_BOARDING_DATE) == date(
        2026, 11, 20
    )
    assert boards_on_other_calendar_day(analysis, 1, 2)
    assert not boards_on_other_calendar_day(analysis, 1, 1)


def test_train_start_date_when_source_is_on_route_day_two() -> None:
    analysis = analyze_route(OVERNIGHT)
    # A passenger boarding at TCR (route day 2) on 21 Nov rides the train that started on 20 Nov.
    assert train_start_date(date(2026, 11, 21), analysis, source_index=3) == date(2026, 11, 20)


def test_scheduled_datetimes_are_ist() -> None:
    analysis = analyze_route(OVERNIGHT)
    start = date(2026, 11, 20)
    assert scheduled_departure(start, analysis, 2) == datetime(2026, 11, 21, 0, 8, tzinfo=IST)
    assert scheduled_arrival(start, analysis, 2) == datetime(2026, 11, 20, 23, 58, tzinfo=IST)
    assert scheduled_departure(start, analysis, 5) is None
