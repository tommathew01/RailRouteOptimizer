"""RailKit payload → domain models. Defensive: every field is optional until proven otherwise.

Structural surprises raise :class:`ProviderInvalidResponseError` (segment outcome
``INVALID_RESPONSE``), never a fabricated status. Unrecognized status text maps to ``UNKNOWN``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.redaction import sanitize_payload
from app.domain.models import (
    AvailabilityQuery,
    AvailabilityRecord,
    Fare,
    Station,
    TrainRoute,
    TrainStop,
    TrainSummary,
    is_valid_station_code,
    is_valid_train_number,
)
from app.domain.prediction import parse_prediction
from app.domain.status_parsing import reconcile_status_fields
from app.integrations.railkit.client import PROVIDER_NAME
from app.integrations.railkit.dates import parse_clock_time, parse_railkit_date
from app.providers.errors import ProviderInvalidResponseError

FARE_BASIS = "RAILKIT_SEAT_AVAILABILITY_TOTAL_FARE"
_DURATION = re.compile(r"^\s*(\d{1,3}):(\d{2})")
_HALT = re.compile(r"^\s*(\d{1,4})\s*(?:m|min|mins|minutes)?\s*$", re.IGNORECASE)


def _invalid(endpoint: str, message: str, **diagnostics: Any) -> ProviderInvalidResponseError:
    return ProviderInvalidResponseError(
        message, provider=PROVIDER_NAME, endpoint=endpoint, diagnostics=diagnostics
    )


# --- Coercion helpers ----------------------------------------------------------------------------
def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _code(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    code = text.upper()
    return code if is_valid_station_code(code) else None


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _train_number(value: object) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and 10_000 <= value <= 99_999:
        return str(value)
    text = _text(value)
    return text if text is not None and is_valid_train_number(text) else None


def _duration_minutes(value: object) -> int | None:
    text = _text(value)
    if text is None or not (match := _DURATION.match(text)):
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _halt_minutes(minutes: object, text: object) -> int | None:
    if (value := _int(minutes)) is not None and value >= 0:
        return value
    halt_text = _text(text)
    if halt_text is not None and (match := _HALT.match(halt_text)):
        return int(match.group(1))
    return None


def _platform(value: object) -> str | None:
    number = _int(value)
    return str(number) if number is not None else _text(value)


def _classes(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    codes = [item.strip().upper() for item in value if isinstance(item, str) and item.strip()]
    return tuple(dict.fromkeys(codes))


# --- Station search ------------------------------------------------------------------------------
def map_stations(data: object) -> list[Station]:
    items: Iterable[object]
    if isinstance(data, Mapping) and isinstance(data.get("stations"), list):
        items = data["stations"]
    elif isinstance(data, list):
        items = data
    else:
        raise _invalid("station_search", "station search data has no stations list")
    stations: list[Station] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        code, name = _code(item.get("code")), _text(item.get("name"))
        if code is None or name is None or code in seen:
            continue
        seen.add(code)
        stations.append(
            Station(
                code=code,
                name=name,
                city=_text(item.get("city")),
                latitude=_float(item.get("lat")),
                longitude=_float(item.get("lon")),
            )
        )
    return stations


def map_station(data: object) -> Station | None:
    """``GET /api/v1/stations/{code}`` → ``{code, name, lat, lon}`` (verified 2026-11-14)."""
    if not isinstance(data, Mapping):
        raise _invalid("station_lookup", "station lookup data is not an object")
    stations = map_stations([data])
    return stations[0] if stations else None


# --- Trains between stations ---------------------------------------------------------------------
def map_train_search(data: object) -> list[TrainSummary]:
    if not isinstance(data, list):
        raise _invalid("train_search", "train search data is not a list")
    trains: list[TrainSummary] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, Mapping):
            continue
        number = _train_number(item.get("train_no"))
        from_code, to_code = _code(item.get("from_stn_code")), _code(item.get("to_stn_code"))
        if number is None or from_code is None or to_code is None or number in seen:
            continue
        seen.add(number)
        trains.append(
            TrainSummary(
                train_number=number,
                train_name=_text(item.get("train_name")),
                from_station_code=from_code,
                to_station_code=to_code,
                from_station_name=_text(item.get("from_stn_name")),
                to_station_name=_text(item.get("to_stn_name")),
                origin_station_code=_code(item.get("source_stn_code")),
                terminus_station_code=_code(item.get("dstn_stn_code")),
                departure_time=parse_clock_time(item.get("from_time")),
                arrival_time=parse_clock_time(item.get("to_time")),
                duration_minutes=_duration_minutes(item.get("travel_time")),
                running_days=_text(item.get("running_days")),
                distance_km=_int(item.get("distance")),
                halts=_int(item.get("halts")),
            )
        )
    return trains


# --- Train info / route --------------------------------------------------------------------------
def map_train_route(data: object, *, train_number: str, fetched_at: datetime) -> TrainRoute:
    if not isinstance(data, Mapping):
        raise _invalid("train_info", "train info data is not an object")
    info = data.get("trainInfo")
    route = data.get("route")
    if not isinstance(route, list):
        raise _invalid("train_info", "train info has no route list")
    anomalies: list[str] = []
    name: str | None = None
    classes: tuple[str, ...] | None = None
    running_days: str | None = None
    if isinstance(info, Mapping):
        echoed = _train_number(info.get("train_no"))
        if echoed is not None and echoed != train_number:
            raise _invalid("train_info", "train number echo mismatch", echoed=echoed)
        name = _text(info.get("train_name"))
        classes = _classes(info.get("classes"))
        running_days = _text(info.get("running_days"))
    else:
        anomalies.append("TRAIN_INFO_MISSING")

    stops: list[TrainStop] = []
    for index, item in enumerate(route):
        if not isinstance(item, Mapping):
            anomalies.append(f"ROUTE_ITEM_NOT_OBJECT:{index}")
            stops.append(TrainStop(index, "", None, None, None, None))
            continue
        raw_code = _text(item.get("stnCode"))
        day = _int(item.get("day"))
        stops.append(
            TrainStop(
                sequence=index,
                station_code=raw_code.upper() if raw_code else "",
                station_name=_text(item.get("stnName")),
                arrival_time=parse_clock_time(item.get("arrival")),
                departure_time=parse_clock_time(item.get("departure")),
                day_offset=day - 1 if day is not None and day >= 1 else None,
                halt_minutes=_halt_minutes(item.get("haltMinutes"), item.get("halt")),
                distance_km=_float(item.get("distance")),
                platform=_platform(item.get("platform")),
                is_stoppage=None,
            )
        )
    return TrainRoute(
        train_number=train_number,
        train_name=name,
        stops=tuple(stops),
        provider=PROVIDER_NAME,
        fetched_at=fetched_at,
        classes=classes,
        running_days=running_days,
        anomalies=tuple(anomalies),
    )


# --- Seat availability ---------------------------------------------------------------------------
_ECHO_FIELDS = ("trainNo", "from", "to", "travelClass", "quota")


def _check_echo(train: object, query: AvailabilityQuery, anomalies: list[str]) -> None:
    if not isinstance(train, Mapping):
        anomalies.append("ECHO_MISSING:train")
        return
    expected = {
        "trainNo": query.train_number,
        "from": query.from_station,
        "to": query.to_station,
        "travelClass": query.travel_class,
        "quota": query.quota.value,
    }
    for name in _ECHO_FIELDS:
        actual = train.get(name)
        if actual is None:
            anomalies.append(f"ECHO_MISSING:{name}")
        elif str(actual).strip().upper() != expected[name].upper():
            raise _invalid(
                "seat_availability",
                f"availability response echoes a different {name}",
                field=name,
                expected=expected[name],
                actual=str(actual)[:20],
            )


def _fare(data: Mapping[str, Any], currency: str, anomalies: list[str]) -> Fare | None:
    fare = data.get("fare")
    if fare is None:
        return None
    total = fare.get("totalFare") if isinstance(fare, Mapping) else None
    number = _float(total)
    if number is None or number <= 0:
        anomalies.append("FARE_INVALID")
        return None
    try:
        amount = Decimal(str(number)).quantize(Decimal("0.01"))
    except InvalidOperation:
        anomalies.append("FARE_INVALID")
        return None
    return Fare(amount=amount, currency=currency, basis=FARE_BASIS)


def map_availability(
    data: object,
    query: AvailabilityQuery,
    *,
    fare_currency: str,
    secret_fragments: Iterable[str] = (),
) -> AvailabilityRecord:
    if not isinstance(data, Mapping):
        raise _invalid("seat_availability", "availability data is not an object")
    anomalies: list[str] = []
    _check_echo(data.get("train"), query, anomalies)

    entries = data.get("availability")
    if not isinstance(entries, list):
        raise _invalid("seat_availability", "availability list missing")
    selected: Mapping[str, Any] | None = None
    seen_dates: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            anomalies.append("AVAILABILITY_ENTRY_NOT_OBJECT")
            continue
        raw_date = entry.get("date")
        seen_dates.append(str(raw_date)[:20])
        entry_date = parse_railkit_date(raw_date, reference=query.journey_date)
        if entry_date is None:
            anomalies.append("AVAILABILITY_DATE_UNPARSEABLE")
        elif entry_date == query.journey_date:
            if selected is None:
                selected = entry
            else:
                anomalies.append("DUPLICATE_DATE_ENTRIES")
    if selected is None:
        raise _invalid(
            "seat_availability",
            "requested date not present in availability list",
            requested=query.journey_date.isoformat(),
            returned=seen_dates[:10],
        )

    reconciled = reconcile_status_fields(
        ("rawStatus", selected.get("rawStatus")),
        ("availabilityText", selected.get("availabilityText")),
        ("status", selected.get("status")),
    )
    anomalies.extend(reconciled.anomalies)
    parsed = reconciled.parsed

    prediction = parse_prediction(
        provider=PROVIDER_NAME,
        text=selected.get("prediction"),
        percentage=selected.get("predictionPercentage"),
    )
    anomalies.extend(prediction.anomalies)

    can_book_raw = selected.get("canBook")
    can_book = can_book_raw if isinstance(can_book_raw, bool) else None
    if can_book_raw is not None and can_book is None:
        anomalies.append("CAN_BOOK_INVALID")

    return AvailabilityRecord(
        status=parsed.status,
        provider=PROVIDER_NAME,
        raw_status=_text(selected.get("rawStatus")),
        availability_text=_text(selected.get("availabilityText")),
        provider_status=_text(selected.get("status")),
        waitlist_type=parsed.waitlist_type,
        waitlist_number=parsed.waitlist_number,
        rac_number=parsed.rac_number,
        available_count=parsed.available_count,
        can_book=can_book,
        prediction=prediction.prediction,
        fare=_fare(data, fare_currency, anomalies),
        provider_checked_at=None,  # RailKit supplies no check timestamp (docs/08 D-12)
        anomalies=tuple(dict.fromkeys(anomalies)),
        raw_payload=sanitize_payload(data, fragments=secret_fragments),
    )
