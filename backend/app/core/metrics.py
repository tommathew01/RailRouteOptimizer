"""Prometheus metrics (doc 06 §4). Labels never contain secrets or user data."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

PROVIDER_REQUESTS = Counter(
    "railroute_provider_requests_total",
    "Provider HTTP attempts by endpoint and outcome (includes retries).",
    ["provider", "endpoint", "outcome"],
    registry=REGISTRY,
)
PROVIDER_LATENCY = Histogram(
    "railroute_provider_latency_seconds",
    "Provider HTTP attempt latency.",
    ["provider", "endpoint"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 30),
    registry=REGISTRY,
)
QUOTA_REFUSALS = Counter(
    "railroute_provider_quota_refusals_total",
    "Provider calls refused by the server-side quota guard.",
    ["provider", "reason"],
    registry=REGISTRY,
)
CACHE_LOOKUPS = Counter(
    "railroute_cache_lookups_total",
    "Cache lookups by kind and result (hit, miss, shared).",
    ["kind", "result"],
    registry=REGISTRY,
)
MALFORMED_RESPONSES = Counter(
    "railroute_provider_malformed_responses_total",
    "Provider responses rejected as invalid.",
    ["provider", "endpoint"],
    registry=REGISTRY,
)
SEARCHES = Counter(
    "railroute_searches_total",
    "Completed journey searches by completeness.",
    ["completeness"],
    registry=REGISTRY,
)
SEARCH_DURATION = Histogram(
    "railroute_search_duration_seconds",
    "Wall-clock duration of journey searches.",
    buckets=(0.5, 1, 2, 5, 10, 20, 40, 60, 90, 120),
    registry=REGISTRY,
)
SEARCH_RESULTS = Histogram(
    "railroute_search_recommendations",
    "Recommendations returned per search.",
    buckets=(0, 1, 2, 5, 10, 20, 50),
    registry=REGISTRY,
)
SEARCH_BUDGET_USED = Histogram(
    "railroute_search_availability_requests",
    "Provider availability requests spent per search.",
    buckets=(0, 1, 2, 5, 10, 20, 30, 50, 100),
    registry=REGISTRY,
)
PREDICTION_COVERAGE = Histogram(
    "railroute_prediction_coverage_ratio",
    "Share of RAC/WL segments in returned recommendations that carry a provider percentage.",
    buckets=(0, 0.25, 0.5, 0.75, 1.0),
    registry=REGISTRY,
)
ACTIVE_SEARCHES = Gauge(
    "railroute_active_searches",
    "Searches currently executing in this process.",
    registry=REGISTRY,
)
