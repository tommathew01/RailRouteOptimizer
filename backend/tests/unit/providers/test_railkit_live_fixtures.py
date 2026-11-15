"""Contract regression tests on sanitized live RailKit payloads (captured 2026-11-14, paid plan).

These pin the adapter to what RailKit actually returns, not only to its documentation samples.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.domain.enums import AvailabilityStatus
from app.domain.models import AvailabilityQuery
from app.domain.route import analyze_route, departure_day, validate_journey
from app.integrations.railkit.mapper import map_availability, map_train_route, map_train_search
from app.providers.errors import ProviderInvalidResponseError
from tests.unit.providers.railkit_helpers import FIXTURES

LIVE = FIXTURES / "live" / "2026-11-14"


def live(name: str) -> Any:
    return json.loads((LIVE / name).read_text(encoding="utf-8"))


def test_availability_lists_the_next_run_dates_and_the_requested_one_is_selected() -> None:
    # 12248 runs on Saturdays only: RailKit returns the next four *run dates*, not four days.
    data = live("seat_availability_direct.json")
    assert [entry["date"] for entry in data["availability"]] == [
        "28-11-2026",
        "5-12-2026",
        "12-12-2026",
        "19-12-2026",
    ]
    for requested, raw, percentage in [
        (date(2026, 11, 28), "GNWL86/WL60", 82.0),
        (date(2026, 12, 5), "GNWL59/WL50", 88.0),  # echoed as "5-12-2026" (no zero padding)
    ]:
        query = AvailabilityQuery("12248", "NZM", "BDTS", requested, "CC")
        record = map_availability(data, query, fare_currency="INR")
        assert record.status is AvailabilityStatus.WAITLIST
        assert record.raw_status == raw
        assert record.waitlist_type == "GNWL"
        assert record.can_book is True  # bookable yet waitlisted
        assert record.prediction is not None
        assert record.prediction.percentage == percentage
        assert record.anomalies == ()


def test_after_midnight_segment_uses_boarding_dates_and_available_carries_a_100_estimate() -> None:
    """RTM is reached on the train's day 2: its availability is listed by RTM boarding date."""
    data = live("seat_availability_after_midnight_boarding_date.json")
    sundays = [date(2026, 11, 29) + timedelta(days=7 * i) for i in range(4)]
    query = AvailabilityQuery("12248", "RTM", "BDTS", sundays[-1], "CC")
    record = map_availability(data, query, fare_currency="INR")
    assert record.status is AvailabilityStatus.AVAILABLE
    assert record.available_count == 19
    # RailKit attaches "Available"/100 to available seats: ranking must not let it reorder
    # all-available paths (decision D-03).
    assert record.prediction is not None
    assert (record.prediction.text, record.prediction.percentage) == ("Available", 100.0)
    assert record.fare is not None
    assert record.fare.amount == Decimal("645.00")
    first = map_availability(data, replace(query, journey_date=sundays[0]), fare_currency="INR")
    assert (first.status, first.waitlist_number) == (AvailabilityStatus.WAITLIST, 3)


def test_date_outside_returned_window_is_invalid_not_unavailable() -> None:
    query = AvailabilityQuery("12248", "NZM", "BDTS", date(2026, 11, 29), "CC")  # not a run date
    with pytest.raises(ProviderInvalidResponseError, match="requested date"):
        map_availability(live("seat_availability_direct.json"), query, fare_currency="INR")


def test_live_probe_report_records_boarding_date_semantics() -> None:
    report = live("report.json")
    assert report["Q1"]["verdict"] == "SEGMENT_BOARDING_DATE"
    assert report["Q1"]["probes"]["train_start_date"]["error"].startswith("REJECTED 400")


def test_train_search_matches_station_clusters_not_exact_stations() -> None:
    trains = map_train_search(live("train_search.json"))
    assert len(trains) == 17
    assert {t.from_station_code for t in trains} == {"NDLS", "NZM", "DEE"}  # searched NDLS
    assert {t.to_station_code for t in trains} == {
        "BDTS",
        "BSR",
        "CSMT",
        "MMCT",
        "PNVL",
    }  # searched BCT
    assert not [t for t in trains if (t.from_station_code, t.to_station_code) == ("NDLS", "BCT")]
    special = next(t for t in trains if t.train_number == "01484")  # leading zero preserved
    assert special.departure_time == time(22, 10)


def test_running_days_are_monday_first_and_search_is_date_filtered() -> None:
    saturday = date(2026, 11, 28)
    trains = map_train_search(live("train_search.json"))
    running = [t.running_days for t in trains]
    assert all(r is not None and r[saturday.weekday()] == "1" for r in running)


def test_live_route_is_verified_and_stop_only() -> None:
    route = map_train_route(
        live("train_info_12904.json"), train_number="12904", fetched_at=datetime.now(UTC)
    )
    assert len(route.stops) == 34
    assert route.classes == ("1A", "2A", "3A", "SL", "GEN", "PWD")
    assert all((s.halt_minutes or 0) > 0 for s in route.stops[1:-1])  # stoppages only
    analysis = analyze_route(route)
    assert analysis.verified
    journey = validate_journey(analysis, "NZM", "BDTS")
    assert journey.verified
    assert journey.source_index is not None
    assert departure_day(analysis, journey.source_index) == 1  # boards NZM on the train's day 2
    assert validate_journey(analysis, "NDLS", "BDTS").verified is False  # 12904 skips NDLS
