"""Persistence records exchanged between services and the persistence gateway."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.domain.enums import (
    IncompleteReason,
    SearchCompleteness,
    SearchStatus,
    SegmentQueryOutcome,
)
from app.domain.models import SegmentKey


@dataclass
class SearchRecord:
    id: uuid.UUID
    source: str
    destination: str
    journey_date: date
    classes: list[str]
    filters: dict[str, Any]
    train_numbers: list[str] | None
    max_segments: int
    request_budget: int
    provider: str
    created_at: datetime
    quota: str = "GN"
    status: SearchStatus = SearchStatus.QUEUED
    search_completeness: SearchCompleteness | None = None
    incomplete_reason: IncompleteReason | None = None
    requests_made: int = 0
    cache_hits: int = 0
    error_code: str | None = None
    result_snapshot: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SegmentRunRecord:
    id: uuid.UUID
    search_id: uuid.UUID | None
    key: SegmentKey
    provider_date: date
    outcome: SegmentQueryOutcome
    cache_hit: bool
    created_at: datetime
    latency_ms: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    observation_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class RecommendationSegmentRecord:
    sequence_index: int
    from_station: str
    to_station: str
    observation_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class RecommendationRecord:
    id: uuid.UUID
    search_id: uuid.UUID
    rank: int
    train_number: str
    train_name: str | None
    travel_class: str
    quota: str
    train_start_date: date
    segment_count: int
    status_tier: int
    fare_complete: bool
    created_at: datetime
    segments: tuple[RecommendationSegmentRecord, ...]
    ranking_metadata: dict[str, Any] = field(default_factory=dict)
    total_fare: Decimal | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderUsageRecord:
    id: uuid.UUID
    provider: str
    endpoint: str
    outcome: str
    attempt: int
    created_at: datetime
    status_code: int | None = None
    latency_ms: float | None = None
    search_id: uuid.UUID | None = None
    request_count: int = 1
