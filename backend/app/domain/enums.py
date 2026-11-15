"""Domain vocabulary. Standard library only — no framework or provider imports."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class AvailabilityStatus(StrEnum):
    """Normalized *current* availability (doc 01 §7). Never derived from a prediction."""

    CONFIRMED = "CONFIRMED"
    AVAILABLE = "AVAILABLE"
    RAC = "RAC"
    WAITLIST = "WAITLIST"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    UNKNOWN = "UNKNOWN"


class Quota(StrEnum):
    """Reservation quotas RailRoute can search (docs/08 D-20). Never mixed within one journey."""

    GENERAL = "GN"
    TATKAL = "TQ"

    @property
    def label(self) -> str:
        return QUOTA_LABELS[self]


QUOTA_LABELS: dict[Quota, str] = {
    Quota.GENERAL: "General",
    Quota.TATKAL: "Tatkal",
}

#: Canonical order: results, combinations and summaries always list quotas in this order.
QUOTA_ORDER: tuple[Quota, ...] = (Quota.GENERAL, Quota.TATKAL)


class TravelClass(StrEnum):
    """Class codes documented by RailKit. Which ones are *enabled* is a setting."""

    FIRST_AC = "1A"
    SECOND_AC = "2A"
    THIRD_AC = "3A"
    THIRD_AC_ECONOMY = "3E"
    SLEEPER = "SL"
    AC_CHAIR_CAR = "CC"
    EXECUTIVE_CHAIR_CAR = "EC"
    SECOND_SITTING = "2S"
    EXECUTIVE_ANUBHUTI = "EA"
    FIRST_CLASS = "FC"
    VISTADOME_NON_AC = "VS"
    CHAIR_CAR_HIGH_CAPACITY = "CH"
    SLEEPER_HIGH_CAPACITY = "HS"
    VISTADOME_CHAIR_CAR = "VC"
    VISTADOME_AC = "VA"

    @property
    def label(self) -> str:
        return CLASS_LABELS[self]


CLASS_LABELS: dict[TravelClass, str] = {
    TravelClass.FIRST_AC: "First AC",
    TravelClass.SECOND_AC: "AC 2 Tier",
    TravelClass.THIRD_AC: "AC 3 Tier",
    TravelClass.THIRD_AC_ECONOMY: "AC 3 Economy",
    TravelClass.SLEEPER: "Sleeper",
    TravelClass.AC_CHAIR_CAR: "AC Chair Car",
    TravelClass.EXECUTIVE_CHAIR_CAR: "Executive Chair Car",
    TravelClass.SECOND_SITTING: "Second Sitting",
    TravelClass.EXECUTIVE_ANUBHUTI: "Executive Anubhuti",
    TravelClass.FIRST_CLASS: "First Class",
    TravelClass.VISTADOME_NON_AC: "Vistadome Non-AC",
    TravelClass.CHAIR_CAR_HIGH_CAPACITY: "Chair Car (High Capacity)",
    TravelClass.SLEEPER_HIGH_CAPACITY: "Sleeper (High Capacity)",
    TravelClass.VISTADOME_CHAIR_CAR: "Vistadome Chair Car",
    TravelClass.VISTADOME_AC: "Vistadome AC",
}

KNOWN_CLASS_CODES: frozenset[str] = frozenset(c.value for c in TravelClass)


class AvailabilityDatePolicy(StrEnum):
    """Which calendar date is sent to the provider for a segment (decision D-02)."""

    #: Date on which the train departs the segment's from-station (IRCTC convention).
    SEGMENT_BOARDING_DATE = "SEGMENT_BOARDING_DATE"
    #: The train's originating (start) date for every segment.
    TRAIN_START_DATE = "TRAIN_START_DATE"


class SegmentQueryOutcome(StrEnum):
    """Outcome of one availability query attempt (doc 02 §8, plus D-11 and quota guard)."""

    SUCCESS = "SUCCESS"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_ERROR = "AUTH_ERROR"
    NOT_FOUND = "NOT_FOUND"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"


class StatusTier(IntEnum):
    """Hard ranking tier of a path (doc 04 §5). Lower is better."""

    ALL_CONFIRMED_OR_AVAILABLE = 0
    INCLUDES_RAC = 1
    INCLUDES_WAITLIST = 2


class SearchStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SearchCompleteness(StrEnum):
    """Doc 03 §10."""

    COMPLETE = "COMPLETE"
    PARTIAL_BUDGET = "PARTIAL_BUDGET"
    PARTIAL_PROVIDER_ERRORS = "PARTIAL_PROVIDER_ERRORS"
    PARTIAL_TIMEOUT = "PARTIAL_TIMEOUT"
    #: Some selected quota combinations were deliberately not queried (e.g. Tatkal not open yet).
    PARTIAL_QUOTA_NOT_QUERIED = "PARTIAL_QUOTA_NOT_QUERIED"
    NO_PATH_FOUND = "NO_PATH_FOUND"
    NO_PATH_FOUND_PARTIAL = "NO_PATH_FOUND_PARTIAL"


class IncompleteReason(StrEnum):
    AVAILABILITY_REQUEST_BUDGET_REACHED = "AVAILABILITY_REQUEST_BUDGET_REACHED"
    PROVIDER_QUOTA_GUARD_REACHED = "PROVIDER_QUOTA_GUARD_REACHED"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_AUTH_ERROR = "PROVIDER_AUTH_ERROR"
    PROVIDER_ERRORS = "PROVIDER_ERRORS"
    SEARCH_DEADLINE_REACHED = "SEARCH_DEADLINE_REACHED"
    QUOTA_NOT_QUERIED = "QUOTA_NOT_QUERIED"
