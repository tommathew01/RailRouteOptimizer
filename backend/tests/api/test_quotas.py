"""Tatkal (TQ) through the public API (docs/08 D-20..D-26).

Frozen clock: 2026-11-08 10:00 UTC = 15:30 IST. Demo train 90601 boards TIR on its origin day; 90602
reaches TIR on route day 2. Tatkal opens one day before the origin date, 10:00 (AC) / 11:00 IST.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from app.core.clock import FrozenClock
from app.domain.enums import Quota
from app.providers.mock.dataset import demo_trains
from app.providers.mock.provider import MockRailwayProvider
from app.repositories.memory import InMemoryPersistence
from app.schemas.journeys import JourneySearchResponse
from tests.api.conftest import api_client, container_of, optimize_body
from tests.conftest import make_settings

NOT_OPEN_DATE = "2026-11-20"  # origin 20 Nov → Tatkal opens 19 Nov
OPEN_DATE = "2026-11-09"  # origin 9 Nov → Tatkal opened 8 Nov 10:00 (AC) / 11:00 (non-AC)
GENEROUS = {"search_max_availability_requests": 200}


def queried_quotas(provider: MockRailwayProvider) -> list[str]:
    return [q.quota.value for q in provider.availability_queries]


def class_rows(body: dict[str, Any], quota: str) -> list[dict[str, Any]]:
    return [c for t in body["trains"] for c in t["classes"] if c["quota"] == quota]


def strip(recs: list[dict[str, Any]]) -> list[Any]:
    """Recommendation content without per-run identifiers (observation ids)."""
    return [
        (
            r["train_number"],
            r["travel_class"],
            r["quota"],
            [(s["source"], s["destination"], s["status"], s["raw_status"]) for s in r["segments"]],
        )
        for r in recs
    ]


def summary(body: dict[str, Any], quota: str) -> dict[str, Any]:
    [item] = [q for q in body["quotas"] if q["quota"] == quota]
    result: dict[str, Any] = item
    return result


async def optimize(**overrides: Any) -> tuple[dict[str, Any], MockRailwayProvider]:
    provider = overrides.pop("provider", None) or MockRailwayProvider()
    settings = overrides.pop("settings", None) or make_settings(**GENEROUS)
    async with api_client(settings, provider=provider) as (client, _):
        response = await client.post("/api/v1/journeys/optimize", json=optimize_body(**overrides))
    assert response.status_code == 200, response.text
    return response.json(), provider


# --- General is unchanged -------------------------------------------------------------------------
async def test_general_only_search_is_unchanged_and_reports_its_quota() -> None:
    default, default_provider = await optimize()
    explicit, _ = await optimize(quotas=["gn"])
    assert default["request"]["quotas"] == ["GN"]
    assert default["request"]["quota"] == "GN"
    assert set(queried_quotas(default_provider)) == {"GN"}
    assert strip(default["recommendations"]) == strip(explicit["recommendations"])
    assert all(r["quota"] == "GN" for r in default["recommendations"])
    assert all(r["quota_label"] == "General" for r in default["recommendations"])
    [general] = default["quotas"]
    assert general["queried"] is True
    assert general["combinations_not_queried"] == 0
    assert default["search_completeness"] != "PARTIAL_QUOTA_NOT_QUERIED"
    assert {c["eligibility"]["state"] for c in class_rows(default, "GN")} == {"NOT_APPLICABLE"}


async def test_closed_tatkal_does_not_change_general_results_or_spend_budget() -> None:
    general_only, gn_provider = await optimize(journey_date=NOT_OPEN_DATE)
    with_tatkal, tq_provider = await optimize(journey_date=NOT_OPEN_DATE, quotas=["GN", "TQ"])
    assert gn_provider.availability_queries == tq_provider.availability_queries
    assert (
        general_only["coverage"]["availability_requests_made"]
        == with_tatkal["coverage"]["availability_requests_made"]
    )
    assert strip(general_only["recommendations"]) == strip(with_tatkal["recommendations"])


# --- Tatkal before / after its window -------------------------------------------------------------
async def test_tatkal_is_not_queried_before_its_window_and_is_not_called_unavailable() -> None:
    body, provider = await optimize(journey_date=NOT_OPEN_DATE, quotas=["GN", "TQ"])
    assert "TQ" not in queried_quotas(provider)
    assert body["request"]["quotas"] == ["GN", "TQ"]
    rows = class_rows(body, "TQ")
    assert rows
    for row in rows:
        assert row["state"] == "NOT_YET_OPEN"
        assert row["queried"] is False
        assert row["eligibility"]["state"] == "NOT_YET_OPEN"
        assert row["eligibility"]["opens_at"] == "2026-11-19T10:00:00+05:30"  # 3A is AC
        assert row["eligibility"]["train_origin_date"] == NOT_OPEN_DATE
    tatkal = summary(body, "TQ")
    assert tatkal["queried"] is False
    assert tatkal["combinations_eligible"] == 0
    assert tatkal["combinations_not_queried"] == len(rows)
    assert tatkal["next_opening_at"] == "2026-11-19T10:00:00+05:30"
    assert tatkal["not_queried"][0]["state"] == "NOT_YET_OPEN"
    assert body["search_completeness"] == "PARTIAL_QUOTA_NOT_QUERIED"
    assert body["incomplete_reason"] == "QUOTA_NOT_QUERIED"
    assert body["coverage"]["combinations_not_queried"] == len(rows)
    assert any("Tatkal (TQ) was not checked" in w and "not open yet" in w for w in body["warnings"])
    assert all(r["quota"] == "GN" for r in body["recommendations"])


async def test_tatkal_only_search_before_opening_spends_nothing_and_is_partial() -> None:
    body, provider = await optimize(journey_date=NOT_OPEN_DATE, quotas=["TQ"])
    assert provider.calls["seat_availability"] == 0
    assert body["coverage"]["availability_requests_made"] == 0
    assert body["recommendations"] == []
    assert body["search_completeness"] == "NO_PATH_FOUND_PARTIAL"  # never "none exist"
    assert body["incomplete_reason"] == "QUOTA_NOT_QUERIED"
    assert not any("is available with these filters" in w for w in body["warnings"])


async def test_tatkal_is_queried_from_the_opening_second_without_automatic_requery() -> None:
    clock = FrozenClock(datetime(2026, 11, 8, 4, 29, 59, tzinfo=UTC))  # 09:59:59 IST
    provider = MockRailwayProvider()
    persistence = InMemoryPersistence()
    request = optimize_body(journey_date=OPEN_DATE, quotas=["GN", "TQ"])
    async with api_client(
        make_settings(**GENEROUS), provider=provider, clock=clock, persistence=persistence
    ) as (client, _):
        before = (await client.post("/api/v1/journeys/optimize", json=request)).json()
        assert {r["state"] for r in class_rows(before, "TQ")} == {"NOT_YET_OPEN"}
        assert class_rows(before, "TQ")[0]["eligibility"]["state"] == "OPENS_TODAY"
        assert "TQ" not in queried_quotas(provider)

        clock.advance(1)  # 10:00:00 IST: open. Nothing is re-queried on its own.
        polled = (await client.get(before["status_url"])).json()
        assert "TQ" not in queried_quotas(provider)
        assert summary(polled, "TQ")["queried"] is False

        after = (await client.post("/api/v1/journeys/optimize", json=request)).json()
    assert "TQ" in queried_quotas(provider)
    assert {c["eligibility"]["state"] for c in class_rows(after, "TQ")} == {"OPEN"}
    assert summary(after, "TQ")["queried"] is True
    quotas = {r["quota"] for r in after["recommendations"]}
    assert "TQ" in quotas
    for rec in after["recommendations"]:  # quotas are never mixed inside a journey
        segment_quotas = {
            persistence.observations[uuid.UUID(s["observation_id"])].key.quota.value
            for s in rec["segments"]
        }
        assert segment_quotas == {rec["quota"]}
        label = "Tatkal (TQ) quota" if rec["quota"] == "TQ" else "General (GN) quota"
        assert all(label in step for step in rec["booking_steps"] if step.startswith("Ticket"))


async def test_origin_date_not_boarding_date_opens_the_window() -> None:
    # 90602 reaches TIR on route day 2: boarding 10 Nov means the train started on 9 Nov, so its
    # Tatkal window opened 8 Nov 10:00 IST (open now). The boarding date would say 9 Nov (closed).
    body, provider = await optimize(
        source="TIR", destination="CLT", journey_date="2026-11-10", quotas=["TQ"]
    )
    [row] = class_rows(body, "TQ")
    assert row["eligibility"]["train_origin_date"] == "2026-11-09"
    assert row["eligibility"]["state"] == "OPEN"
    assert row["queried"] is True
    tatkal_dates = {q.journey_date.isoformat() for q in provider.availability_queries}
    assert tatkal_dates == {"2026-11-10"}  # the provider still gets the boarding date
    assert set(queried_quotas(provider)) == {"TQ"}


# --- Provider support -----------------------------------------------------------------------------
async def test_unsupported_tatkal_is_reported_and_never_substituted() -> None:
    provider = MockRailwayProvider(quotas=(Quota.GENERAL,))  # Tatkal switched off at the provider
    body, _ = await optimize(provider=provider, journey_date=OPEN_DATE, quotas=["GN", "TQ"])
    assert set(queried_quotas(provider)) == {"GN"}
    assert {r["state"] for r in class_rows(body, "TQ")} == {"QUOTA_NOT_SUPPORTED"}
    tatkal = summary(body, "TQ")
    assert tatkal["provider_supported"] is False
    assert tatkal["queried"] is False
    assert any("not supported" in w and "No other quota" in w for w in body["warnings"])
    assert {r["quota"] for r in body["recommendations"]} <= {"GN"}


async def test_unsupported_only_quota_is_refused_before_any_provider_call() -> None:
    provider = MockRailwayProvider(quotas=(Quota.GENERAL,))
    async with api_client(provider=provider) as (client, _):
        response = await client.post("/api/v1/journeys/optimize", json=optimize_body(quotas=["TQ"]))
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "QUOTA_NOT_SUPPORTED"
    assert error["details"]["supported_quotas"] == ["GN"]
    assert sum(provider.calls.values()) == 0


async def test_unclassified_class_is_not_queried_for_tatkal() -> None:
    trains = dict(demo_trains())
    trains["90605"] = replace(trains["90605"], classes=("CC", "2S", "CH"))
    provider = MockRailwayProvider(trains=trains)
    settings = make_settings(supported_classes="CC,CH", **GENEROUS)
    body, _ = await optimize(
        provider=provider,
        settings=settings,
        source="TCR",
        destination="TVC",
        journey_date=OPEN_DATE,
        classes=["CH"],
        quotas=["GN", "TQ"],
    )
    assert ("CH", "TQ") not in {
        (q.travel_class, q.quota.value) for q in provider.availability_queries
    }
    assert ("CH", "GN") in {(q.travel_class, q.quota.value) for q in provider.availability_queries}
    [row] = [r for r in class_rows(body, "TQ") if r["state"] != "NOT_OFFERED"]  # only 90605
    assert row["state"] == "NOT_QUERIED"
    assert row["eligibility"]["state"] == "CLASS_CATEGORY_UNKNOWN"
    assert row["eligibility"]["class_category"] is None


# --- Cache, dedupe, budget ------------------------------------------------------------------------
async def test_no_segment_is_requested_twice_within_a_search() -> None:
    _, provider = await optimize(journey_date=OPEN_DATE, quotas=["GN", "TQ"])
    queries = provider.availability_queries
    assert len(queries) == len(set(queries))


async def test_budget_is_shared_by_all_quotas_and_reported() -> None:
    settings = make_settings(search_max_availability_requests=6)
    body, provider = await optimize(
        settings=settings, journey_date=OPEN_DATE, quotas=["GN", "TQ"], classes=["3A", "SL"]
    )
    made = body["coverage"]["availability_requests_made"]
    assert made == len(provider.availability_queries) <= 6
    assert body["search_completeness"] in ("PARTIAL_BUDGET", "NO_PATH_FOUND_PARTIAL")
    assert body["incomplete_reason"] == "AVAILABILITY_REQUEST_BUDGET_REACHED"


async def test_quota_answers_are_cached_separately() -> None:
    provider = MockRailwayProvider()
    segment = {
        "train_number": "90601",
        "source": "TIR",
        "destination": "ERS",
        "journey_date": OPEN_DATE,
        "travel_class": "3A",
    }
    async with api_client(provider=provider) as (client, _):
        general = (await client.post("/api/v1/availability/check", json=segment)).json()
        tatkal = (
            await client.post("/api/v1/availability/check", json={**segment, "quota": "TQ"})
        ).json()
        tatkal_again = (
            await client.post("/api/v1/availability/check", json={**segment, "quota": "tq"})
        ).json()
    assert (general["quota"], general["cached"]) == ("GN", False)
    assert (tatkal["quota"], tatkal["cached"], tatkal["queried"]) == ("TQ", False, True)
    assert tatkal_again["cached"] is True
    assert queried_quotas(provider) == ["GN", "TQ"]
    assert tatkal["fare"]["amount"] != general["fare"]["amount"]


# --- Single-segment availability endpoint -------------------------------------------------------
async def test_availability_check_before_opening_returns_eligibility_not_status() -> None:
    provider = MockRailwayProvider()
    async with api_client(provider=provider) as (client, _):
        response = await client.post(
            "/api/v1/availability/check",
            json={
                "train_number": "90601",
                "source": "TIR",
                "destination": "TVC",
                "journey_date": NOT_OPEN_DATE,
                "travel_class": "SL",
                "quota": "TQ",
            },
        )
    data = response.json()
    assert response.status_code == 200
    assert (data["queried"], data["availability"], data["checked_at"]) == (False, None, None)
    assert data["eligibility"]["state"] == "NOT_YET_OPEN"
    assert data["eligibility"]["class_category"] == "NON_AC"
    assert data["eligibility"]["opens_at"] == "2026-11-19T11:00:00+05:30"
    assert data["train_start_date"] == NOT_OPEN_DATE
    assert provider.calls["seat_availability"] == 0
    assert any("opens on 19 Nov 2026 at 11:00 IST" in w for w in data["warnings"])


async def test_availability_check_unsupported_quota_needs_no_provider_call() -> None:
    provider = MockRailwayProvider(quotas=(Quota.GENERAL,))
    async with api_client(provider=provider) as (client, _):
        data = (
            await client.post(
                "/api/v1/availability/check",
                json={
                    "train_number": "90601",
                    "source": "TIR",
                    "destination": "TVC",
                    "journey_date": OPEN_DATE,
                    "travel_class": "3A",
                    "quota": "TQ",
                },
            )
        ).json()
        unknown = [
            await client.post(
                "/api/v1/availability/check",
                json={
                    "train_number": "90601",
                    "source": "TIR",
                    "destination": "TVC",
                    "journey_date": OPEN_DATE,
                    "travel_class": "3A",
                    "quota": code,
                },
            )
            for code in ("LD", "PT")  # PT (Premium Tatkal) is not offered
        ]
    assert data["queried"] is False
    assert data["eligibility"]["state"] == "PROVIDER_UNSUPPORTED"
    assert sum(provider.calls.values()) == 0
    assert [r.status_code for r in unknown] == [400, 400]


# --- Meta and backward compatibility --------------------------------------------------------------
async def test_meta_lists_quotas_with_provider_support_and_opening_rules() -> None:
    provider = MockRailwayProvider(quotas=(Quota.GENERAL,))
    async with api_client(provider=provider) as (client, _):
        body = (await client.get("/api/v1/meta")).json()
    async with api_client() as (client, _):  # default mock supports every offered quota
        full = (await client.get("/api/v1/meta")).json()
    options = {q["code"]: q for q in body["quotas"]}
    assert list(options) == ["GN", "TQ"]  # no Premium Tatkal
    assert options["GN"]["default"] is True
    assert options["GN"]["opening_rule"] is None
    assert options["TQ"]["opening_rule"] == {
        "reference": "TRAIN_ORIGIN_DATE",
        "days_before": 1,
        "ac_opens_at": "10:00",
        "non_ac_opens_at": "11:00",
        "timezone": "Asia/Kolkata",
    }
    assert options["TQ"]["provider_supported"] is False
    assert options["TQ"]["note"]
    assert {q["code"]: q["provider_supported"] for q in full["quotas"]} == {"GN": True, "TQ": True}


async def test_snapshots_from_before_quota_support_still_load() -> None:
    body, _ = await optimize()
    legacy = dict(body)
    legacy.pop("quotas")
    legacy["request"] = {k: v for k, v in body["request"].items() if k != "quotas"}
    legacy["coverage"] = {
        k: v for k, v in body["coverage"].items() if k != "combinations_not_queried"
    }
    legacy["recommendations"] = [
        {k: v for k, v in r.items() if k != "quota_label"} for r in body["recommendations"]
    ]
    legacy["trains"] = [
        {
            **t,
            "classes": [
                {
                    k: v
                    for k, v in c.items()
                    if k not in ("quota", "quota_label", "queried", "eligibility")
                }
                for c in t["classes"]
            ],
        }
        for t in body["trains"]
    ]
    restored = JourneySearchResponse.model_validate(legacy)
    assert restored.request.quotas == ["GN"]
    assert restored.quotas == []
    assert all(r.quota_label == "General" for r in restored.recommendations)


async def test_invalid_quota_is_rejected() -> None:
    async with api_client() as (client, application):
        rejected = [
            await client.post("/api/v1/journeys/optimize", json=optimize_body(quotas=quotas))
            for quotas in (["GN", "LD"], ["GN", "PT"], ["PT"], [], ["TQ", "tq"])
        ]
        assert container_of(application).provider.supported_quotas == frozenset(Quota)
    # Unknown codes (including the removed Premium Tatkal "PT") and an empty list are 400s;
    # duplicates are collapsed rather than rejected.
    assert [r.status_code for r in rejected[:4]] == [400, 400, 400, 400]
    assert rejected[4].status_code == 200
    assert rejected[4].json()["request"]["quotas"] == ["TQ"]
