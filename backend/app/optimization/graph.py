"""Forward-only segment graph for one train run, class and quota (doc 04 §2).

Edges exist only for successfully queried, eligible segments. Adding an observation from a
different train, start date, class or quota is rejected — paths can never mix them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from app.domain.enums import Quota, StatusTier
from app.domain.models import SegmentObservation
from app.optimization.policy import EdgeEligibility, SearchFilters, classify, status_tier


class GraphConsistencyError(ValueError):
    """An edge does not belong to this graph (different train/date/class/quota or backward)."""


@dataclass(frozen=True, slots=True)
class GraphKey:
    train_number: str
    train_start_date: date
    travel_class: str
    quota: Quota = Quota.GENERAL


@dataclass(frozen=True, slots=True)
class SegmentEdge:
    from_index: int
    to_index: int
    observation: SegmentObservation
    tier: StatusTier

    @property
    def from_station(self) -> str:
        return self.observation.key.from_station

    @property
    def to_station(self) -> str:
        return self.observation.key.to_station


@dataclass
class SegmentGraph:
    key: GraphKey
    _outgoing: dict[int, dict[int, SegmentEdge]] = field(default_factory=dict)

    def add(self, edge: SegmentEdge) -> None:
        obs_key = edge.observation.key
        actual = GraphKey(
            obs_key.train_number, obs_key.train_start_date, obs_key.travel_class, obs_key.quota
        )
        if actual != self.key:
            raise GraphConsistencyError(f"edge {actual} does not belong to graph {self.key}")
        if edge.from_index >= edge.to_index:
            raise GraphConsistencyError("edges must move forward along the route")
        self._outgoing.setdefault(edge.from_index, {})[edge.to_index] = edge

    def is_available(self, from_index: int, to_index: int) -> bool:
        """Is there a CONFIRMED/AVAILABLE segment from ``from_index`` to ``to_index``?"""
        edge = self._outgoing.get(from_index, {}).get(to_index)
        return edge is not None and edge.tier is StatusTier.ALL_CONFIRMED_OR_AVAILABLE

    def outgoing(self, index: int) -> list[SegmentEdge]:
        """Deterministic order: nearest destination first."""
        edges = self._outgoing.get(index, {})
        return [edges[to] for to in sorted(edges)]

    @property
    def edge_count(self) -> int:
        return sum(len(edges) for edges in self._outgoing.values())


def build_graph(
    key: GraphKey,
    observations: Iterable[SegmentObservation],
    station_index: Mapping[str, int],
    filters: SearchFilters,
) -> SegmentGraph:
    """``station_index`` maps the route's (unique) boundary station codes to route positions."""
    graph = SegmentGraph(key)
    for observation in observations:
        if classify(observation.record.status, filters) is not EdgeEligibility.USABLE:
            continue
        tier = status_tier(observation.record.status)
        from_index = station_index.get(observation.key.from_station)
        to_index = station_index.get(observation.key.to_station)
        if tier is None or from_index is None or to_index is None:
            continue
        graph.add(SegmentEdge(from_index, to_index, observation, tier))
    return graph
