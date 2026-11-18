"""Cache key formats (doc 06 §3), extended with the provider and both dates of a segment."""

from __future__ import annotations

import re
from datetime import date

from app.domain.models import SegmentKey

_SPACES = re.compile(r"\s+")


def availability(provider: str, key: SegmentKey, provider_date: date) -> str:
    return (
        f"availability:{provider}:{key.train_number}:{key.train_start_date.isoformat()}:"
        f"{provider_date.isoformat()}:{key.from_station}:{key.to_station}:"
        f"{key.travel_class}:{key.quota.value}"
    )


def train_search(provider: str, source: str, destination: str, journey_date: date) -> str:
    return f"train-search:{provider}:{source}:{destination}:{journey_date.isoformat()}"


def train_route(provider: str, train_number: str) -> str:
    return f"train-route:{provider}:{train_number}"


def normalize_station_query(query: str) -> str:
    return _SPACES.sub(" ", query.strip().lower())


def station_search(provider: str, query: str) -> str:
    return f"station-search:{provider}:{normalize_station_query(query)}"


def station_code(provider: str, code: str) -> str:
    return f"station-code:{provider}:{code.upper()}"


def search_stop(search_id: str) -> str:
    """Set when a user stops a search; read by whichever process runs it (docs/08 D-35)."""
    return f"search-stop:{search_id}"


def lock(key: str) -> str:
    return f"lock:{key}"
