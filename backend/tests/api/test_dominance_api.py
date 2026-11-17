"""Redundant split tickets through the public API (docs/08 D-34). Mock provider.

Demo train 90601, SL, with the screenshots' pattern: every leg short of TVC is AVAILABLE and
every leg into TVC is waitlisted. Only "TIR → stop" + "stop → TVC" combinations are useful; any
further split of an available "TIR → stop" leg is dominated and must be neither shown nor
requested.
"""

from __future__ import annotations

from typing import Any

from app.providers.mock.dataset import demo_trains
from app.providers.mock.provider import MockRailwayProvider
from tests.api.conftest import api_client, optimize_body
from tests.conftest import make_settings


def screenshot_pattern() -> MockRailwayProvider:
    codes = [stop.code for stop in demo_trains()["90601"].stops]
    section = codes[codes.index("TIR") : codes.index("TVC") + 1]
    overrides: dict[Any, Any] = {}
    for i, a in enumerate(section):
        for b in section[i + 1 :]:
            overrides[("90601", a, b, "SL")] = (
                ("GNWL35/WL24", "59% Chance", 59) if b == "TVC" else ("AVAILABLE-0025", None, None)
            )
    return MockRailwayProvider(overrides=overrides)


async def test_no_redundant_split_is_shown_or_requested() -> None:
    provider = screenshot_pattern()
    settings = make_settings(search_max_availability_requests=300, railkit_max_concurrency=8)
    body = optimize_body(
        classes=["SL"],
        train_numbers=["90601"],
        filters={"allow_rac": True, "allow_waitlist": True},
    )
    async with api_client(settings, provider=provider) as (client, _):
        result = (await client.post("/api/v1/journeys/optimize", json=body)).json()

    [train] = result["trains"]
    stops = train["intermediate_stops_considered"]
    queries = provider.availability_queries
    # The direct ticket, every TIR→stop and every stop→TVC — and nothing in between.
    assert len(queries) == 1 + 2 * stops
    assert all(q.from_station == "TIR" or q.to_station == "TVC" for q in queries)
    assert result["coverage"]["availability_requests_made"] == len(queries)

    recommendations = result["recommendations"]
    assert recommendations
    for rec in recommendations:  # every option is "TIR → stop (AVL)" + "stop → TVC (WL)"
        assert rec["segment_count"] <= 2
        assert [s["status"] for s in rec["segments"]][-1] == "WAITLIST"
    two_ticket = [r for r in recommendations if r["segment_count"] == 2]
    assert len({r["segments"][0]["destination"] for r in two_ticket}) == len(two_ticket)
    assert all(r["segments"][0]["status"] == "AVAILABLE" for r in two_ticket)
    assert all(r["segments"][-1]["prediction"]["percentage"] == 59 for r in two_ticket)
