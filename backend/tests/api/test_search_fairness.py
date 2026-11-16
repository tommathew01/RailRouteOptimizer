"""Fair budget allocation, class/train limits and the search preview through the public API
(docs/08 D-27..D-30). Mock provider, frozen clock: 2026-11-08 15:30 IST.

Five copies of demo train 90603 (1A, 2A, 3A, SL; boards TIR on its origin day) give the review's
worst case: 5 trains x 4 classes x 2 quotas = 40 combinations. Journey date 2026-11-09: Tatkal
opened on 8 Nov at 10:00 (AC) / 11:00 (non-AC), so every Tatkal combination is queryable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any

from app.domain.enums import Quota
from app.providers.mock.dataset import demo_trains
from app.providers.mock.provider import MockRailwayProvider
from tests.api.conftest import api_client, optimize_body
from tests.conftest import make_settings

TRAINS = ("90611", "90613", "90615", "90617", "90619")
CLASSES = ["1A", "2A", "3A", "SL"]
OPEN_DATE = "2026-11-09"
NOT_OPEN_DATE = "2026-11-20"


def five_trains() -> MockRailwayProvider:
    base = demo_trains()["90603"]
    return MockRailwayProvider(trains={n: replace(base, number=n) for n in TRAINS})


def grid_settings(**overrides: Any) -> Any:
    values: dict[str, Any] = {"search_max_classes": 4, "railkit_max_concurrency": 8}
    values.update(overrides)
    return make_settings(**values)


async def optimize(settings: Any, provider: MockRailwayProvider, **body: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "journey_date": OPEN_DATE,
        "classes": CLASSES,
        "quotas": ["GN", "TQ"],
        "train_numbers": list(TRAINS),
    }
    payload = optimize_body(**(defaults | body))
    async with api_client(settings, provider=provider) as (client, _):
        response = await client.post("/api/v1/journeys/optimize", json=payload)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def directs(provider: MockRailwayProvider) -> list[tuple[str, str, str]]:
    return [
        (q.train_number, q.travel_class, q.quota.value)
        for q in provider.availability_queries
        if (q.from_station, q.to_station) == ("TIR", "TVC")
    ]


def class_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for t in body["trains"] for c in t["classes"]]


async def test_forty_combinations_each_get_their_direct_check_before_any_split() -> None:
    provider = five_trains()
    body = await optimize(grid_settings(search_max_availability_requests=100), provider)
    coverage = body["coverage"]
    assert coverage["combinations_evaluated"] == 40
    assert coverage["combinations_not_reached"] == 0
    checked = directs(provider)
    assert len(checked) == len(set(checked)) == 40  # every train x class x quota, once
    first_forty = provider.availability_queries[:40]
    assert all((q.from_station, q.to_station) == ("TIR", "TVC") for q in first_forty)
    rows = class_rows(body)
    assert len(rows) == 40
    assert all(row["queried"] and row["segments_queried"] >= 1 for row in rows)
    assert {s["quota"]: s["queried"] for s in body["quotas"]} == {"GN": True, "TQ": True}


async def test_budget_below_the_combinations_splits_directs_evenly_between_quotas() -> None:
    provider = five_trains()
    body = await optimize(grid_settings(search_max_availability_requests=30), provider)
    checked = directs(provider)
    assert len(provider.availability_queries) == len(checked) == 30  # nothing deeper
    assert Counter(quota for _, _, quota in checked) == {"GN": 15, "TQ": 15}
    assert body["coverage"]["combinations_not_reached"] == 10
    assert body["incomplete_reason"] == "AVAILABILITY_REQUEST_BUDGET_REACHED"
    unreached = [r for r in class_rows(body) if not r["queried"]]
    assert len(unreached) == 10
    assert all(r["state"] == "STOPPED" for r in unreached)  # not checked, never "unavailable"


async def test_logical_checks_and_attempts_are_reported_separately() -> None:
    body = await optimize(grid_settings(search_max_availability_requests=60), five_trains())
    coverage = body["coverage"]
    # The mock provider never retries: one attempt per logical check.
    assert coverage["availability_requests_made"] == coverage["availability_checks_made"] == 60
    assert coverage["availability_retries"] == coverage["availability_retries_refused"] == 0
    assert coverage["request_budget"] == 60


async def test_recommendations_never_mix_quotas_or_classes() -> None:
    body = await optimize(grid_settings(search_max_availability_requests=200), five_trains())
    assert body["recommendations"]
    for rec in body["recommendations"]:
        assert rec["quota"] in ("GN", "TQ")
        assert rec["train_number"] in TRAINS
        assert all(s["status"] for s in rec["segments"])
    assert {r["quota"] for r in body["recommendations"]} <= {"GN", "TQ"}


async def test_general_only_search_is_unaffected_by_the_quota_interleaving() -> None:
    """A GN-only search queries exactly what the GN half of a GN+TQ search queries first."""
    gn_provider, both_provider = five_trains(), five_trains()
    settings = grid_settings(search_max_availability_requests=20)
    await optimize(settings, gn_provider, quotas=["GN"])
    assert len(directs(gn_provider)) == 20
    assert {q for _, _, q in directs(gn_provider)} == {"GN"}
    await optimize(grid_settings(search_max_availability_requests=40), both_provider)
    gn_half = [d for d in directs(both_provider) if d[2] == "GN"]
    assert sorted(gn_half) == sorted(directs(gn_provider))


async def test_closed_tatkal_is_skipped_and_its_budget_goes_to_general() -> None:
    provider = five_trains()
    body = await optimize(
        grid_settings(search_max_availability_requests=40), provider, journey_date=NOT_OPEN_DATE
    )
    assert {q.quota for q in provider.availability_queries} == {Quota.GENERAL}
    assert body["coverage"]["combinations_not_queried"] == 20
    assert body["coverage"]["combinations_not_reached"] == 0
    assert len(provider.availability_queries) == 40  # 20 directs + 20 deeper GN checks
    tatkal = [r for r in class_rows(body) if r["quota"] == "TQ"]
    assert all(r["state"] == "NOT_YET_OPEN" and not r["queried"] for r in tatkal)


# --- Class and train limits ---------------------------------------------------------------------
async def test_more_classes_than_the_limit_are_refused_not_truncated() -> None:
    provider = five_trains()
    async with api_client(make_settings(), provider=provider) as (client, _):
        response = await client.post(
            "/api/v1/journeys/optimize", json=optimize_body(classes=CLASSES)
        )
        preview = await client.post("/api/v1/journeys/preview", json=optimize_body(classes=CLASSES))
    for result in (response, preview):
        assert result.status_code == 400
        error = result.json()["error"]
        assert error["code"] == "TOO_MANY_CLASSES"
        assert "at most 3 classes" in error["message"]
    assert provider.calls == Counter()  # refused before any provider request


async def test_meta_publishes_the_limits_the_server_enforces() -> None:
    settings = make_settings(search_max_trains=4, search_default_trains=2, search_max_classes=2)
    async with api_client(settings) as (client, _):
        limits = (await client.get("/api/v1/meta")).json()["limits"]
    assert limits["max_trains_per_search"] == 4
    assert limits["default_trains_selected"] == 2
    assert limits["max_classes_per_search"] == 2
    assert limits["max_availability_requests_per_search"] == 30


async def test_default_limits_are_five_trains_three_preselected_three_classes() -> None:
    async with api_client() as (client, _):
        limits = (await client.get("/api/v1/meta")).json()["limits"]
    assert (
        limits["max_trains_per_search"],
        limits["default_trains_selected"],
        limits["max_classes_per_search"],
    ) == (5, 3, 3)


# --- Preview ------------------------------------------------------------------------------------
async def preview(settings: Any, provider: MockRailwayProvider, **body: Any) -> dict[str, Any]:
    payload = optimize_body(
        journey_date=OPEN_DATE, classes=CLASSES[:3], quotas=["GN", "TQ"], train_numbers=list(TRAINS)
    )
    payload.update(body)
    async with api_client(settings, provider=provider) as (client, _):
        response = await client.post("/api/v1/journeys/preview", json=payload)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_preview_counts_exactly_what_the_search_queries_and_spends_nothing() -> None:
    provider = five_trains()
    plan = await preview(make_settings(), provider)
    assert provider.calls["seat_availability"] == 0
    assert plan["combinations"] == 30  # 5 trains x 3 classes x 2 quotas
    assert plan["request_budget"] == 30
    assert plan["covers_direct_checks"] is True
    assert plan["requests_per_combination"] == 1.0
    assert {q["quota"]: q["combinations"] for q in plan["quotas"]} == {"GN": 15, "TQ": 15}
    assert "No requests are left for split-ticket alternatives" in " ".join(plan["explanation"])

    search_provider = five_trains()
    body = await optimize(make_settings(), search_provider, classes=CLASSES[:3])
    assert body["coverage"]["combinations_evaluated"] == plan["combinations"]
    planned = {(p["train_number"], p["travel_class"], p["quota"]) for p in plan["planned"]}
    assert planned == set(directs(search_provider))


async def test_preview_reports_closed_tatkal_and_budget_shortfall() -> None:
    plan = await preview(
        make_settings(search_max_availability_requests=10),
        five_trains(),
        journey_date=NOT_OPEN_DATE,
    )
    assert plan["combinations"] == 15  # General only: Tatkal opens on 19 Nov
    assert plan["combinations_not_queried"] == 15
    [tatkal] = [q for q in plan["quotas"] if q["quota"] == "TQ"]
    assert tatkal["combinations"] == 0
    assert tatkal["next_opening_at"] is not None
    assert any("not open yet" in note for note in tatkal["notes"])
    assert plan["covers_direct_checks"] is False
    assert "only 10 of the 15" in plan["explanation"][0]


async def test_preview_with_spare_budget_explains_the_depth_trade_off() -> None:
    plan = await preview(
        make_settings(search_max_availability_requests=100),
        five_trains(),
        train_numbers=list(TRAINS[:2]),
        classes=["3A"],
    )
    assert plan["combinations"] == 4
    assert plan["trains_selected"] == 2
    assert plan["requests_per_combination"] == 25.0
    text = " ".join(plan["explanation"])
    assert "remaining 96 requests" in text
    assert "leaves less depth for each" in text


async def test_no_premium_tatkal_anywhere() -> None:
    provider = five_trains()
    assert {q.value for q in Quota} == {"GN", "TQ"}
    async with api_client(make_settings(), provider=provider) as (client, _):
        meta = (await client.get("/api/v1/meta")).json()
        refused = await client.post(
            "/api/v1/journeys/preview", json=optimize_body(quotas=["GN", "PT"])
        )
    assert [q["code"] for q in meta["quotas"]] == ["GN", "TQ"]
    assert refused.status_code == 400
    assert provider.calls == Counter()
