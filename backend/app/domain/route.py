"""Route validation, timeline (day offsets / midnight crossing) and segment date rules (doc 03).

Route order is the provider's order; it is never re-sorted. A route that cannot be trusted is
``ROUTE_UNVERIFIED`` and yields no recommendations.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from app.domain.enums import AvailabilityDatePolicy
from app.domain.models import TrainRoute, is_valid_station_code
from app.domain.time import MINUTES_PER_DAY, ist_datetime, minutes_of_day


class RouteIssue(StrEnum):
    # Fatal for the whole route
    EMPTY_ROUTE = "EMPTY_ROUTE"
    INVALID_STATION_CODE = "INVALID_STATION_CODE"
    MISSING_DAY_OFFSET = "MISSING_DAY_OFFSET"
    DAY_OFFSET_DECREASING = "DAY_OFFSET_DECREASING"
    DAY_OFFSET_GAP = "DAY_OFFSET_GAP"
    TIME_ORDER_INCONSISTENT = "TIME_ORDER_INCONSISTENT"
    # Fatal for a specific journey
    SAME_SOURCE_AND_DESTINATION = "SAME_SOURCE_AND_DESTINATION"
    SOURCE_NOT_ON_ROUTE = "SOURCE_NOT_ON_ROUTE"
    DESTINATION_NOT_ON_ROUTE = "DESTINATION_NOT_ON_ROUTE"
    SOURCE_AFTER_DESTINATION = "SOURCE_AFTER_DESTINATION"
    SOURCE_AMBIGUOUS = "SOURCE_AMBIGUOUS"
    DESTINATION_AMBIGUOUS = "DESTINATION_AMBIGUOUS"
    # Warnings: the stop is excluded as a segment boundary, the route stays usable
    DUPLICATE_STATION = "DUPLICATE_STATION"
    STOP_TIME_MISSING = "STOP_TIME_MISSING"
    NOT_A_STOPPAGE = "NOT_A_STOPPAGE"


ROUTE_FATAL = frozenset(
    {
        RouteIssue.EMPTY_ROUTE,
        RouteIssue.INVALID_STATION_CODE,
        RouteIssue.MISSING_DAY_OFFSET,
        RouteIssue.DAY_OFFSET_DECREASING,
        RouteIssue.DAY_OFFSET_GAP,
        RouteIssue.TIME_ORDER_INCONSISTENT,
    }
)
JOURNEY_FATAL = ROUTE_FATAL | {
    RouteIssue.SAME_SOURCE_AND_DESTINATION,
    RouteIssue.SOURCE_NOT_ON_ROUTE,
    RouteIssue.DESTINATION_NOT_ON_ROUTE,
    RouteIssue.SOURCE_AFTER_DESTINATION,
    RouteIssue.SOURCE_AMBIGUOUS,
    RouteIssue.DESTINATION_AMBIGUOUS,
}


@dataclass(frozen=True, slots=True)
class StopTimeline:
    """Absolute minutes are counted from 00:00 IST on the train's start date."""

    sequence: int
    station_code: str
    arrival_minutes: int | None
    departure_minutes: int | None

    @property
    def departure_day(self) -> int | None:
        if self.departure_minutes is not None:
            return self.departure_minutes // MINUTES_PER_DAY
        if self.arrival_minutes is not None:
            return self.arrival_minutes // MINUTES_PER_DAY
        return None


@dataclass(frozen=True, slots=True)
class RouteAnalysis:
    route: TrainRoute
    issues: tuple[RouteIssue, ...]
    timeline: tuple[StopTimeline, ...]
    duplicate_stations: frozenset[str]
    excluded_boundaries: frozenset[int]

    @property
    def verified(self) -> bool:
        return not any(issue in ROUTE_FATAL for issue in self.issues)

    def indices_of(self, station_code: str) -> list[int]:
        return [s.sequence for s in self.route.stops if s.station_code == station_code]


def _timeline(route: TrainRoute) -> list[StopTimeline]:
    timeline: list[StopTimeline] = []
    for stop in route.stops:
        if stop.day_offset is None:
            timeline.append(StopTimeline(stop.sequence, stop.station_code, None, None))
            continue
        base = stop.day_offset * MINUTES_PER_DAY
        arrival = base + minutes_of_day(stop.arrival_time) if stop.arrival_time else None
        departure: int | None = None
        if stop.departure_time is not None:
            if arrival is not None:
                # Departure may fall after midnight during the halt (e.g. 23:58 → 00:08).
                departure = (
                    arrival + (minutes_of_day(stop.departure_time) - arrival) % MINUTES_PER_DAY
                )
            else:
                departure = base + minutes_of_day(stop.departure_time)
        timeline.append(StopTimeline(stop.sequence, stop.station_code, arrival, departure))
    return timeline


def analyze_route(route: TrainRoute) -> RouteAnalysis:
    issues: list[RouteIssue] = []
    stops = route.stops
    if len(stops) < 2:
        issues.append(RouteIssue.EMPTY_ROUTE)
    if any(not is_valid_station_code(stop.station_code) for stop in stops):
        issues.append(RouteIssue.INVALID_STATION_CODE)
    if any(stop.day_offset is None for stop in stops):
        issues.append(RouteIssue.MISSING_DAY_OFFSET)

    days = [stop.day_offset for stop in stops if stop.day_offset is not None]
    if any(later < earlier for earlier, later in itertools.pairwise(days)):
        issues.append(RouteIssue.DAY_OFFSET_DECREASING)
    if any(later - earlier > 1 for earlier, later in itertools.pairwise(days)):
        issues.append(RouteIssue.DAY_OFFSET_GAP)

    timeline = _timeline(route)
    last_seen: int | None = None
    for entry in timeline:
        first = (
            entry.arrival_minutes if entry.arrival_minutes is not None else entry.departure_minutes
        )
        if first is not None and last_seen is not None:
            gap = first - last_seen
            if gap < 0 or gap >= MINUTES_PER_DAY:
                issues.append(RouteIssue.TIME_ORDER_INCONSISTENT)
                break
        latest = entry.departure_minutes if entry.departure_minutes is not None else first
        if latest is not None:
            last_seen = latest

    counts: dict[str, int] = {}
    for stop in stops:
        counts[stop.station_code] = counts.get(stop.station_code, 0) + 1
    duplicates = frozenset(code for code, count in counts.items() if count > 1)
    if duplicates:
        issues.append(RouteIssue.DUPLICATE_STATION)

    excluded: set[int] = set()
    for stop, entry in zip(stops, timeline, strict=True):
        if stop.station_code in duplicates:
            excluded.add(stop.sequence)
        if stop.is_stoppage is False:
            excluded.add(stop.sequence)
            issues.append(RouteIssue.NOT_A_STOPPAGE)
        is_terminus = stop.sequence == len(stops) - 1
        if entry.departure_minutes is None and not is_terminus:
            excluded.add(stop.sequence)
            issues.append(RouteIssue.STOP_TIME_MISSING)
    return RouteAnalysis(
        route=route,
        issues=tuple(dict.fromkeys(issues)),
        timeline=tuple(timeline),
        duplicate_stations=duplicates,
        excluded_boundaries=frozenset(excluded),
    )


@dataclass(frozen=True, slots=True)
class JourneyRoute:
    """A route validated for one requested source/destination."""

    analysis: RouteAnalysis
    issues: tuple[RouteIssue, ...]
    source_index: int | None
    destination_index: int | None
    #: Usable segment boundaries in route order: source, eligible intermediates, destination.
    boundary_indices: tuple[int, ...]

    @property
    def verified(self) -> bool:
        return (
            self.source_index is not None
            and self.destination_index is not None
            and not any(issue in JOURNEY_FATAL for issue in self.issues)
        )

    @property
    def intermediate_indices(self) -> tuple[int, ...]:
        return self.boundary_indices[1:-1]

    @property
    def total_intermediate_stops(self) -> int:
        if self.source_index is None or self.destination_index is None:
            return 0
        return max(0, self.destination_index - self.source_index - 1)


def validate_journey(analysis: RouteAnalysis, source: str, destination: str) -> JourneyRoute:
    issues = list(analysis.issues)
    source_hits, destination_hits = analysis.indices_of(source), analysis.indices_of(destination)
    source_index = destination_index = None
    if source == destination:
        issues.append(RouteIssue.SAME_SOURCE_AND_DESTINATION)
    if not source_hits:
        issues.append(RouteIssue.SOURCE_NOT_ON_ROUTE)
    elif len(source_hits) > 1:
        issues.append(RouteIssue.SOURCE_AMBIGUOUS)
    else:
        source_index = source_hits[0]
    if not destination_hits:
        issues.append(RouteIssue.DESTINATION_NOT_ON_ROUTE)
    elif len(destination_hits) > 1:
        issues.append(RouteIssue.DESTINATION_AMBIGUOUS)
    else:
        destination_index = destination_hits[0]
    if (
        source_index is not None
        and destination_index is not None
        and source_index >= destination_index
    ):
        issues.append(RouteIssue.SOURCE_AFTER_DESTINATION)

    boundaries: tuple[int, ...] = ()
    fatal = any(issue in JOURNEY_FATAL for issue in issues)
    if source_index is not None and destination_index is not None and not fatal:
        if source_index in analysis.excluded_boundaries:
            issues.append(RouteIssue.STOP_TIME_MISSING)
            fatal = True
        else:
            middle = tuple(
                index
                for index in range(source_index + 1, destination_index)
                if index not in analysis.excluded_boundaries
            )
            boundaries = (source_index, *middle, destination_index)
    return JourneyRoute(
        analysis=analysis,
        issues=tuple(dict.fromkeys(issues)),
        source_index=source_index,
        destination_index=destination_index,
        boundary_indices=boundaries,
    )


# --- Dates ---------------------------------------------------------------------------------------
def departure_day(analysis: RouteAnalysis, index: int) -> int:
    day = analysis.timeline[index].departure_day
    if day is None:
        raise ValueError(f"stop {index} has no usable time or day offset")
    return day


def train_start_date(journey_date: date, analysis: RouteAnalysis, source_index: int) -> date:
    """``journey_date`` is the date the passenger departs the source station (D-01)."""
    return journey_date - timedelta(days=departure_day(analysis, source_index))


def provider_query_date(
    start_date: date, analysis: RouteAnalysis, from_index: int, policy: AvailabilityDatePolicy
) -> date:
    """The date sent to the provider for a segment boarding at ``from_index`` (D-02)."""
    if policy is AvailabilityDatePolicy.TRAIN_START_DATE:
        return start_date
    return start_date + timedelta(days=departure_day(analysis, from_index))


def boards_on_other_calendar_day(
    analysis: RouteAnalysis, source_index: int, from_index: int
) -> bool:
    return departure_day(analysis, from_index) != departure_day(analysis, source_index)


def scheduled_departure(start_date: date, analysis: RouteAnalysis, index: int) -> datetime | None:
    minutes = analysis.timeline[index].departure_minutes
    return None if minutes is None else ist_datetime(start_date, time(0, 0), minutes)


def scheduled_arrival(start_date: date, analysis: RouteAnalysis, index: int) -> datetime | None:
    minutes = analysis.timeline[index].arrival_minutes
    return None if minutes is None else ist_datetime(start_date, time(0, 0), minutes)
