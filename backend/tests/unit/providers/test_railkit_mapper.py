from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

import pytest

from app.domain.enums import AvailabilityStatus as S
from app.domain.models import AvailabilityQuery, PredictionSource
from app.integrations.railkit.dates import parse_railkit_date, to_railkit_date
from app.integrations.railkit.mapper import (
    map_availability,
    map_stations,
    map_train_route,
    map_train_search,
)
from app.providers.errors import ProviderInvalidResponseError
from tests.unit.providers.railkit_helpers import availability_payload, load_fixture

QUERY = AvailabilityQuery("12904", "NZM", "BDTS", date(2026, 9, 1), "3A")


def _map(payload: dict[str, Any], query: AvailabilityQuery = QUERY) -> Any:
    return map_availability(payload["data"], query, fare_currency="INR")


# --- Dates ---------------------------------------------------------------------------------------
def test_outbound_date_format_is_dd_mm_yyyy() -> None:
    assert to_railkit_date(date(2026, 9, 1)) == "01-09-2026"


@pytest.mark.parametrize(
    "text", ["1-9-2026", "01-09-2026", "2026-09-01", "01/09/2026", "1-Sep-2026", "1 Sep 2026"]
)
def test_echoed_dates_are_parsed_tolerantly(text: str) -> None:
    assert parse_railkit_date(text) == date(2026, 9, 1)


def test_yearless_date_resolves_nearest_year_only_with_reference() -> None:
    assert parse_railkit_date("2 Jan", reference=date(2026, 12, 30)) == date(2027, 1, 2)
    assert parse_railkit_date("2 Jan") is None


@pytest.mark.parametrize("text", [None, "", "tomorrow", "32-01-2026", 20260901])
def test_garbage_dates_are_none(text: object) -> None:
    assert parse_railkit_date(text) is None


# --- Availability --------------------------------------------------------------------------------
def test_documented_sample_maps_status_and_prediction_separately() -> None:
    record = _map(load_fixture("seat_availability_docs.json"))
    assert record.status is S.WAITLIST
    assert record.raw_status == "RLWL31/WL23"
    assert record.availability_text == "WL 23"
    assert record.provider_status == "WAITLIST"
    assert (record.waitlist_type, record.waitlist_number) == ("RLWL", 23)
    assert record.can_book is True  # bookable, yet still waitlisted
    assert record.prediction is not None
    assert record.prediction.text == "73% Chance"
    assert record.prediction.percentage == 73.0
    assert record.prediction.percentage_source is PredictionSource.FIELD
    assert record.fare is not None
    assert record.fare.amount == Decimal("1670.00")
    assert record.fare.currency == "INR"
    assert record.provider == "RAILKIT"
    assert record.provider_checked_at is None  # never fabricated
    assert record.anomalies == ()
    assert record.raw_payload is not None
    assert record.raw_payload["availability"][0]["rawStatus"] == "RLWL31/WL23"


@pytest.mark.parametrize(
    ("raw", "text", "status", "expected"),
    [
        ("AVAILABLE-0012", "AVL 12", "AVAILABLE", S.AVAILABLE),
        ("CNF", "CNF", "CONFIRMED", S.CONFIRMED),
        ("RAC 5", "RAC 5", "RAC", S.RAC),
        ("REGRET/WL", "REGRET", "NOT_AVAILABLE", S.NOT_AVAILABLE),
        ("SOMETHING NEW", "???", "STRANGE", S.UNKNOWN),
        (None, None, None, S.UNKNOWN),
    ],
)
def test_status_variants(
    raw: str | None, text: str | None, status: str | None, expected: S
) -> None:
    record = _map(availability_payload(rawStatus=raw, availabilityText=text, status=status))
    assert record.status is expected


def test_conflicting_status_fields_are_unknown_not_guessed() -> None:
    record = _map(availability_payload(rawStatus="GNWL5/WL3", status="AVAILABLE"))
    assert record.status is S.UNKNOWN
    assert any(a.startswith("STATUS_FIELDS_CONFLICT") for a in record.anomalies)


def test_missing_prediction_does_not_invalidate_segment() -> None:
    record = _map(availability_payload(prediction=..., predictionPercentage=...))
    assert record.status is S.WAITLIST
    assert record.prediction is None


@pytest.mark.parametrize("bad", [140, -3, "abc", True])
def test_malformed_prediction_percentage(bad: object) -> None:
    record = _map(availability_payload(predictionPercentage=bad))
    assert record.prediction is not None
    assert record.prediction.percentage is None
    assert "PREDICTION_PERCENTAGE_INVALID" in record.anomalies
    assert record.status is S.WAITLIST  # status unaffected by prediction problems


def test_can_book_must_be_boolean() -> None:
    record = _map(availability_payload(canBook="yes"))
    assert record.can_book is None
    assert "CAN_BOOK_INVALID" in record.anomalies


def test_requested_date_absent_is_invalid_response() -> None:
    with pytest.raises(ProviderInvalidResponseError, match="requested date"):
        _map(availability_payload(date="2-9-2026"))


def test_correct_entry_is_selected_from_multi_day_list() -> None:
    payload = availability_payload()
    entries = payload["data"]["availability"]
    entries.insert(0, {**entries[0], "date": "31-8-2026", "rawStatus": "AVAILABLE-0001"})
    entries.append({**entries[0], "date": "2-9-2026", "rawStatus": "REGRET/WL"})
    record = _map(payload)
    assert record.raw_status == "RLWL31/WL23"


def test_echo_mismatch_is_invalid_response() -> None:
    payload = availability_payload()
    payload["data"]["train"]["travelClass"] = "SL"
    with pytest.raises(ProviderInvalidResponseError, match="travelClass"):
        _map(payload)


def test_missing_echo_is_accepted_with_anomaly() -> None:
    payload = availability_payload()
    del payload["data"]["train"]["quota"]
    record = _map(payload)
    assert "ECHO_MISSING:quota" in record.anomalies


@pytest.mark.parametrize("broken", [None, [], "x", {"availability": "nope"}, {"train": {}}])
def test_malformed_payload_is_invalid_response(broken: object) -> None:
    with pytest.raises(ProviderInvalidResponseError):
        map_availability(broken, QUERY, fare_currency="INR")


@pytest.mark.parametrize("total", [0, -5, "abc", None, float("nan")])
def test_invalid_fare_is_dropped(total: object) -> None:
    payload = availability_payload()
    payload["data"]["fare"]["totalFare"] = total
    record = _map(payload)
    assert record.fare is None
    assert "FARE_INVALID" in record.anomalies


def test_secrets_are_scrubbed_from_raw_payload() -> None:
    payload = availability_payload(debug="key=rk_secret_12345678")
    payload["data"]["x-api-key"] = "rk_secret_12345678"
    record = map_availability(
        payload["data"], QUERY, fare_currency="INR", secret_fragments=["rk_secret_12345678"]
    )
    assert "rk_secret_12345678" not in str(record.raw_payload)


# --- Train info ----------------------------------------------------------------------------------
NOW = datetime(2026, 11, 8, tzinfo=UTC)


def test_documented_train_info_maps() -> None:
    route = map_train_route(
        load_fixture("train_info_docs.json")["data"], train_number="12345", fetched_at=NOW
    )
    assert route.train_name == "SARAIGHAT EXP"
    assert route.classes == ("1A", "2A", "3A", "SL", "GEN", "PWD")
    stop = route.stops[0]
    assert (stop.station_code, stop.arrival_time, stop.departure_time) == ("HWH", None, time(16, 5))
    assert stop.day_offset == 0
    assert stop.platform == "15"


def test_overnight_route_keeps_order_and_day_offsets() -> None:
    data = load_fixture("train_info_synthetic_overnight.json")["data"]
    route = map_train_route(data, train_number="16999", fetched_at=NOW)
    assert [s.station_code for s in route.stops] == ["CLT", "TIR", "SRR", "TCR", "ERS", "TVC"]
    assert [s.sequence for s in route.stops] == list(range(6))
    assert [s.day_offset for s in route.stops] == [0, 0, 0, 1, 1, 1]
    assert route.stops[2].halt_minutes == 10  # from "10 min" text when haltMinutes is absent
    assert route.stops[1].platform == "2"
    assert route.stops[-1].departure_time is None


def test_train_info_echo_mismatch_is_invalid() -> None:
    with pytest.raises(ProviderInvalidResponseError, match="echo"):
        map_train_route(
            load_fixture("train_info_docs.json")["data"], train_number="54321", fetched_at=NOW
        )


def test_bad_day_values_become_none() -> None:
    data = load_fixture("train_info_synthetic_overnight.json")["data"]
    data["route"][3]["day"] = "x"
    data["route"][4]["day"] = 0
    route = map_train_route(data, train_number="16999", fetched_at=NOW)
    assert route.stops[3].day_offset is None
    assert route.stops[4].day_offset is None


def test_route_must_be_a_list() -> None:
    with pytest.raises(ProviderInvalidResponseError):
        map_train_route({"trainInfo": {}}, train_number="12345", fetched_at=NOW)


# --- Train search / stations ---------------------------------------------------------------------
def test_train_search_maps_documented_fields_only() -> None:
    [train] = map_train_search(load_fixture("train_search_docs.json")["data"])
    assert train.train_number == "12904"
    assert (train.from_station_code, train.to_station_code) == ("NZM", "BDTS")
    assert (train.origin_station_code, train.terminus_station_code) == ("ASR", "BDTS")
    assert train.departure_time == time(4, 0)
    assert train.duration_minutes == 19 * 60 + 55
    assert train.distance_km == 1365


def test_train_search_skips_unusable_rows() -> None:
    rows = load_fixture("train_search_docs.json")["data"]
    rows += [{"train_no": "12"}, {"train_no": 2904, "from_stn_code": "A", "to_stn_code": "B"}, "x"]
    assert [t.train_number for t in map_train_search(rows)] == ["12904"]


def test_station_search_maps_and_dedupes() -> None:
    data = load_fixture("station_search_docs.json")["data"]
    data["stations"].append({"code": "DAZ", "name": "dup"})
    data["stations"].append({"code": "bad code!", "name": "x"})
    stations = map_stations(data)
    assert [s.code for s in stations] == ["ANDI", "DAZ"]
    assert stations[0].latitude == pytest.approx(28.714265)


def test_station_lookup_by_code_maps_playground_payload() -> None:
    from app.integrations.railkit.mapper import map_station

    station = map_station(
        {"code": "TVCN", "name": "THIRUVANANTHAPURAM NORTH", "lat": None, "lon": None}
    )
    assert station is not None
    assert (station.code, station.name, station.latitude) == (
        "TVCN",
        "THIRUVANANTHAPURAM NORTH",
        None,
    )
    assert map_station({"code": "bad code!", "name": "x"}) is None
    with pytest.raises(ProviderInvalidResponseError):
        map_station(["not", "an", "object"])
