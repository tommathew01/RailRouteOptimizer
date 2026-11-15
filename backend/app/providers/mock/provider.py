"""Deterministic mock implementation of :class:`RailwayProvider` (doc 07 §10).

Provider name ``MOCK`` and ``is_live = False`` so every response is labelled as demo data.
Availability is a pure function of (train, segment, date, class); tests can inject failures,
force statuses and count calls.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal

from app.domain.enums import AvailabilityStatus, Quota
from app.domain.models import (
    AvailabilityQuery,
    AvailabilityRecord,
    Fare,
    Station,
    TrainRoute,
    TrainStop,
    TrainSummary,
)
from app.domain.prediction import parse_prediction
from app.domain.status_parsing import reconcile_status_fields
from app.domain.time import MINUTES_PER_DAY
from app.providers.errors import (
    ProviderError,
    ProviderNotFoundError,
    ProviderRejectedError,
)
from app.providers.mock.dataset import (
    CLASS_BIAS,
    DEMO_OVERRIDES,
    FARE_RATE,
    STATIONS,
    MockTrain,
    demo_trains,
)

PROVIDER_NAME = "MOCK"
SegmentKey = tuple[str, str, str, str]  # (train, from, to, class)


def _unit(*parts: str) -> float:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:12], 16) / float(16**12)


def _display_text(raw: str) -> str:
    """Short text in the style of RailKit's ``availabilityText`` (e.g. ``"WL 27"``)."""
    if raw.startswith("AVAILABLE-"):
        return f"AVL {int(raw.removeprefix('AVAILABLE-'))}"
    if "/WL" in raw:
        return "WL " + raw.rsplit("/WL", 1)[1]
    if raw.startswith("REGRET"):
        return "REGRET"
    return raw


def _abs_minutes(train: MockTrain, index: int, *, departure: bool) -> int:
    stop = train.stops[index]
    clock = stop.departure if departure and stop.departure else stop.arrival or stop.departure
    if clock is None:
        raise ValueError(f"stop {stop.code} has no time")
    minutes = (stop.day - 1) * MINUTES_PER_DAY + clock.hour * 60 + clock.minute
    if departure and stop.arrival and stop.departure and stop.departure < stop.arrival:
        minutes += MINUTES_PER_DAY  # midnight during the halt
    return minutes


class MockRailwayProvider:
    def __init__(
        self,
        *,
        latency_ms: int = 0,
        trains: Mapping[str, MockTrain] | None = None,
        overrides: Mapping[SegmentKey, tuple[str, str | None, int | None]] | None = None,
        failures: Mapping[SegmentKey, ProviderError] | None = None,
        clock_now: datetime | None = None,
    ) -> None:
        self._latency = latency_ms / 1000
        self._trains = dict(trains or demo_trains())
        self._overrides = dict(DEMO_OVERRIDES if overrides is None else overrides)
        self.failures: dict[SegmentKey, ProviderError] = dict(failures or {})
        self._now = clock_now
        self.calls: Counter[str] = Counter()
        self.availability_queries: list[AvailabilityQuery] = []

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def is_live(self) -> bool:
        return False

    async def _simulate(self, endpoint: str) -> None:
        self.calls[endpoint] += 1
        if self._latency:
            await asyncio.sleep(self._latency)

    def _train(self, number: str, endpoint: str) -> MockTrain:
        train = self._trains.get(number)
        if train is None:
            raise ProviderNotFoundError(
                "train not found", provider=PROVIDER_NAME, endpoint=endpoint, status_code=404
            )
        return train

    # --- Stations -----------------------------------------------------------------------------
    async def search_stations(self, query: str) -> list[Station]:
        await self._simulate("station_search")
        needle = query.strip().lower()
        ranked = sorted(
            (
                (
                    0
                    if s.code.lower() == needle
                    else 1
                    if s.name.lower().startswith(needle)
                    else 2,
                    s,
                )
                for s in STATIONS.values()
                if needle in s.name.lower() or s.code.lower().startswith(needle)
            ),
            key=lambda pair: (pair[0], pair[1].name),
        )
        return [station for _, station in ranked[:10]]

    async def get_station(self, code: str) -> Station | None:
        await self._simulate("station_lookup")
        return STATIONS.get(code.strip().upper())

    # --- Trains -------------------------------------------------------------------------------
    async def search_trains(
        self, source: str, destination: str, journey_date: date
    ) -> list[TrainSummary]:
        await self._simulate("train_search")
        results: list[tuple[int, TrainSummary]] = []
        for train in self._trains.values():
            i, j = train.index_of(source), train.index_of(destination)
            if i is None or j is None or i >= j:
                continue
            depart = _abs_minutes(train, i, departure=True)
            arrive = _abs_minutes(train, j, departure=False)
            results.append(
                (
                    depart % MINUTES_PER_DAY,
                    TrainSummary(
                        train_number=train.number,
                        train_name=train.name,
                        from_station_code=source,
                        to_station_code=destination,
                        from_station_name=STATIONS[source].name,
                        to_station_name=STATIONS[destination].name,
                        origin_station_code=train.stops[0].code,
                        terminus_station_code=train.stops[-1].code,
                        departure_time=train.stops[i].departure,
                        arrival_time=train.stops[j].arrival,
                        duration_minutes=arrive - depart,
                        running_days=train.running_days,
                        distance_km=train.stops[j].distance_km - train.stops[i].distance_km,
                        halts=j - i - 1,
                    ),
                )
            )
        return [summary for _, summary in sorted(results, key=lambda pair: pair[0])]

    async def get_train_route(self, train_number: str) -> TrainRoute:
        await self._simulate("train_info")
        train = self._train(train_number, "train_info")
        stops = tuple(
            TrainStop(
                sequence=index,
                station_code=stop.code,
                station_name=STATIONS[stop.code].name,
                arrival_time=stop.arrival,
                departure_time=stop.departure,
                day_offset=stop.day - 1,
                halt_minutes=stop.halt_minutes,
                distance_km=float(stop.distance_km),
                platform=None,
                is_stoppage=True,
            )
            for index, stop in enumerate(train.stops)
        )
        return TrainRoute(
            train_number=train.number,
            train_name=train.name,
            stops=stops,
            provider=PROVIDER_NAME,
            fetched_at=self._now or datetime.now(UTC),
            classes=train.classes,
            running_days=train.running_days,
        )

    # --- Availability -------------------------------------------------------------------------
    async def get_availability(self, query: AvailabilityQuery) -> AvailabilityRecord:
        await self._simulate("seat_availability")
        self.availability_queries.append(query)
        key: SegmentKey = (
            query.train_number,
            query.from_station,
            query.to_station,
            query.travel_class,
        )
        if (failure := self.failures.get(key)) is not None:
            raise failure
        train = self._train(query.train_number, "seat_availability")
        i, j = train.index_of(query.from_station), train.index_of(query.to_station)
        if i is None or j is None or i >= j:
            raise ProviderRejectedError(
                "station pair is not served in this order",
                provider=PROVIDER_NAME,
                endpoint="seat_availability",
                status_code=400,
            )
        if query.travel_class not in train.classes or query.quota is not Quota.GENERAL:
            raise ProviderRejectedError(
                "class or quota not offered",
                provider=PROVIDER_NAME,
                endpoint="seat_availability",
                status_code=400,
            )

        raw, prediction_text, percentage = self._status_for(train, i, j, query)
        reconciled = reconcile_status_fields(("rawStatus", raw))
        prediction = parse_prediction(
            provider=PROVIDER_NAME, text=prediction_text, percentage=percentage
        )
        parsed = reconciled.parsed
        distance = train.stops[j].distance_km - train.stops[i].distance_km
        rate, reservation = FARE_RATE.get(query.travel_class, (1.0, 40))
        fare = Decimal(max(round(distance * rate) + reservation, reservation + 10))
        return AvailabilityRecord(
            status=parsed.status,
            provider=PROVIDER_NAME,
            raw_status=raw,
            availability_text=_display_text(raw),
            provider_status=parsed.status.value,
            waitlist_type=parsed.waitlist_type,
            waitlist_number=parsed.waitlist_number,
            rac_number=parsed.rac_number,
            available_count=parsed.available_count,
            can_book=parsed.status
            in {AvailabilityStatus.AVAILABLE, AvailabilityStatus.RAC, AvailabilityStatus.WAITLIST},
            prediction=prediction.prediction,
            fare=Fare(amount=fare, currency="INR", basis="MOCK_DISTANCE_FARE"),
            provider_checked_at=None,
            anomalies=reconciled.anomalies + prediction.anomalies,
            raw_payload={
                "mock": True,
                "rawStatus": raw,
                "prediction": prediction_text,
                "predictionPercentage": percentage,
                "date": query.journey_date.isoformat(),
            },
        )

    def _status_for(
        self, train: MockTrain, i: int, j: int, query: AvailabilityQuery
    ) -> tuple[str, str | None, int | None]:
        key = (query.train_number, query.from_station, query.to_station, query.travel_class)
        if key in self._overrides:
            return self._overrides[key]
        span = (j - i) / max(1, len(train.stops) - 1)
        roll = _unit(*key, query.journey_date.isoformat())
        pressure = 0.55 * roll + 0.75 * span + CLASS_BIAS.get(query.travel_class, 0.0)
        detail = _unit("detail", *key, query.journey_date.isoformat())
        if pressure < 0.40:
            return (f"AVAILABLE-{max(1, round(detail * 90)):04d}", None, None)
        if pressure < 0.55:
            rac = 1 + round(detail * 24)
            return (f"RAC {rac}", f"{max(55, 97 - rac * 2)}% Chance", max(55, 97 - rac * 2))
        if pressure < 1.0:
            booked = 3 + round(detail * 140)
            current = max(1, round(booked * (0.4 + 0.4 * roll)))
            chance = max(3, min(95, round(92 - current * 1.1)))
            if detail > 0.85:  # some waitlists come without any provider prediction
                return (f"GNWL{booked}/WL{current}", None, None)
            return (f"GNWL{booked}/WL{current}", f"{chance}% Chance", chance)
        return ("REGRET/WL", None, None)

    async def aclose(self) -> None:
        return None
