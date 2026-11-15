"""Station search, train search and train route schemas (doc 05 §1-3)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from app.domain.models import Station, TrainRoute, TrainSummary
from app.schemas.common import ApiModel
from app.schemas.shared import DataMode, StationCode


def _hhmm(value: object) -> str | None:
    return None if value is None else value.strftime("%H:%M")  # type: ignore[attr-defined]


class StationOut(ApiModel):
    code: str
    name: str
    city: str | None
    latitude: float | None
    longitude: float | None

    @classmethod
    def of(cls, station: Station) -> StationOut:
        return cls(
            code=station.code,
            name=station.name,
            city=station.city,
            latitude=station.latitude,
            longitude=station.longitude,
        )


class StationSearchResponse(ApiModel):
    items: list[StationOut]
    data_mode: DataMode


class TrainSearchRequest(ApiModel):
    source: StationCode
    destination: StationCode
    journey_date: date = Field(description="Date you depart the source station (IST).")


class TrainOut(ApiModel):
    train_number: str
    train_name: str | None
    boards_at: str = Field(description="Station the provider lists for boarding.")
    boards_at_name: str | None
    alights_at: str
    alights_at_name: str | None
    serves_requested_stations: bool = Field(
        description="False when the provider matched a different (e.g. nearby) station."
    )
    departure_time: str | None = Field(description="HH:MM at the boarding station (IST).")
    arrival_time: str | None
    duration_minutes: int | None
    running_days: str | None = Field(description="Provider's raw running-days string.")
    origin_station_code: str | None
    terminus_station_code: str | None
    distance_km: int | None
    halts: int | None

    @classmethod
    def of(cls, train: TrainSummary, source: str, destination: str) -> TrainOut:
        return cls(
            train_number=train.train_number,
            train_name=train.train_name,
            boards_at=train.from_station_code,
            boards_at_name=train.from_station_name,
            alights_at=train.to_station_code,
            alights_at_name=train.to_station_name,
            serves_requested_stations=(
                train.from_station_code == source and train.to_station_code == destination
            ),
            departure_time=_hhmm(train.departure_time),
            arrival_time=_hhmm(train.arrival_time),
            duration_minutes=train.duration_minutes,
            running_days=train.running_days,
            origin_station_code=train.origin_station_code,
            terminus_station_code=train.terminus_station_code,
            distance_km=train.distance_km,
            halts=train.halts,
        )


class TrainSearchResponse(ApiModel):
    source: str
    destination: str
    journey_date: date
    trains: list[TrainOut]
    data_mode: DataMode
    provider: str


class RouteStopOut(ApiModel):
    sequence: int
    station_code: str
    station_name: str | None
    arrival: str | None
    departure: str | None
    day_offset: int | None = Field(description="0 = the train's starting day.")
    halt_minutes: int | None
    distance_km: float | None
    platform: str | None


class TrainRouteResponse(ApiModel):
    train_number: str
    train_name: str | None
    stops: list[RouteStopOut]
    route_verified: bool
    issues: list[str]
    classes: list[str] | None = Field(description="Classes the provider lists; null if unknown.")
    running_days: str | None
    fetched_at: datetime
    data_mode: DataMode

    @classmethod
    def of(
        cls, route: TrainRoute, *, verified: bool, issues: list[str], data_mode: DataMode
    ) -> TrainRouteResponse:
        return cls(
            train_number=route.train_number,
            train_name=route.train_name,
            stops=[
                RouteStopOut(
                    sequence=s.sequence,
                    station_code=s.station_code,
                    station_name=s.station_name,
                    arrival=_hhmm(s.arrival_time),
                    departure=_hhmm(s.departure_time),
                    day_offset=s.day_offset,
                    halt_minutes=s.halt_minutes,
                    distance_km=s.distance_km,
                    platform=s.platform,
                )
                for s in route.stops
            ],
            route_verified=verified,
            issues=issues,
            classes=list(route.classes) if route.classes is not None else None,
            running_days=route.running_days,
            fetched_at=route.fetched_at,
            data_mode=data_mode,
        )
