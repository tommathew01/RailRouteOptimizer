"""Mutable state of one journey search while it executes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from app.domain.enums import IncompleteReason, Quota
from app.domain.models import SegmentObservation, TrainRoute, TrainSummary
from app.domain.quota_eligibility import QuotaEligibility
from app.domain.route import JourneyRoute, RouteAnalysis
from app.optimization.planner import QueryPlanner
from app.optimization.policy import SearchFilters
from app.services.quota import SearchBudget


@dataclass(frozen=True, slots=True)
class JourneyRequest:
    source: str
    destination: str
    journey_date: date
    classes: tuple[str, ...]
    filters: SearchFilters
    max_segments: int
    train_numbers: tuple[str, ...] | None
    notes: tuple[str, ...] = ()
    #: Canonical order (GN, TQ). Each quota is a separate search space.
    quotas: tuple[Quota, ...] = (Quota.GENERAL,)


@dataclass
class TrainContext:
    summary: TrainSummary | None
    train_number: str
    evaluation: str
    route: TrainRoute | None = None
    analysis: RouteAnalysis | None = None
    journey: JourneyRoute | None = None
    start_date: date | None = None
    considered: tuple[int, ...] = ()
    issues: list[str] = field(default_factory=list)
    #: travel class -> state for classes that were not turned into planner combinations
    class_states: dict[str, str] = field(default_factory=dict)
    #: (travel class, quota) -> booking-window eligibility, for every offered pair evaluated
    eligibility: dict[tuple[str, Quota], QuotaEligibility] = field(default_factory=dict)

    @property
    def name(self) -> str | None:
        if self.route and self.route.train_name:
            return self.route.train_name
        return self.summary.train_name if self.summary else None


@dataclass
class ComboContext:
    combo_id: int
    train: TrainContext
    travel_class: str
    quota: Quota = Quota.GENERAL
    observations: dict[tuple[int, int], SegmentObservation] = field(default_factory=dict)
    cached_observation_ids: set[uuid.UUID] = field(default_factory=set)


@dataclass
class SearchStats:
    trains_found: int = 0
    cache_hits: int = 0
    segments_checked: int = 0
    segments_unknown: int = 0
    segments_failed: int = 0
    route_failures: int = 0
    #: Offered train x class x quota combinations deliberately not queried (eligibility)
    combinations_not_queried: int = 0
    deadline_hit: bool = False
    stop_reason: IncompleteReason | None = None
    hard_stop: bool = False


@dataclass
class SearchContext:
    search_id: uuid.UUID
    request: JourneyRequest
    budget: SearchBudget
    deadline: float
    trains: list[TrainContext] = field(default_factory=list)
    combos: dict[int, ComboContext] = field(default_factory=dict)
    stats: SearchStats = field(default_factory=SearchStats)
    planner: QueryPlanner | None = None
    warnings: list[str] = field(default_factory=list)
    #: The user asked to stop (seen locally or via the shared store); never reset (D-35).
    stop_requested: bool = False
