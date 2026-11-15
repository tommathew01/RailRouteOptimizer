"""Opt-in live RailKit contract checks (docs/09 §6). SPENDS REAL QUOTA (about 5 requests).

Run:  make test-live   (or RUN_LIVE_RAILKIT_TESTS=true uv run pytest tests/live -m live -s)
Needs RAILKIT_API_KEY in the environment or the untracked root .env.
Sanitized payloads and a machine-readable report.json are written to
tests/fixtures/railkit/live/run-<UTC timestamp>/ for review; promote useful ones to a dated folder.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.clock import SystemClock
from app.core.config import ProviderName, Settings
from app.core.redaction import sanitize_payload
from app.domain.enums import KNOWN_CLASS_CODES, AvailabilityDatePolicy, AvailabilityStatus
from app.domain.models import AvailabilityQuery, TrainSummary
from app.domain.route import (
    analyze_route,
    departure_day,
    provider_query_date,
    train_start_date,
    validate_journey,
)
from app.domain.status_parsing import reconcile_status_fields
from app.domain.time import today_ist
from app.integrations.railkit.client import RailKitHttpClient
from app.integrations.railkit.dates import parse_railkit_date, to_railkit_date
from app.integrations.railkit.mapper import map_availability, map_train_route, map_train_search
from app.providers.errors import ProviderError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_RAILKIT_TESTS", "").lower() != "true",
        reason="live RailKit tests are opt-in (RUN_LIVE_RAILKIT_TESTS=true)",
    ),
]

CAPTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "railkit" / "live"
SOURCE, DESTINATION = (
    os.environ.get("LIVE_SOURCE", "NDLS"),
    os.environ.get("LIVE_DESTINATION", "BCT"),
)


def _settings() -> Settings:
    try:
        return Settings(railway_provider=ProviderName.RAILKIT)
    except ValidationError:
        pytest.skip("RAILKIT_API_KEY is not configured")


def _save(folder: Path, name: str, payload: Any, secrets: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    clean = sanitize_payload(payload, fragments=secrets, max_items=400)
    (folder / f"{name}.json").write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n")


def _report(label: str, value: object) -> None:
    print(f"[live] {label}: {value}")  # noqa: T201 (operator-facing contract report)


RUNNING = {
    AvailabilityStatus.AVAILABLE,
    AvailabilityStatus.CONFIRMED,
    AvailabilityStatus.RAC,
    AvailabilityStatus.WAITLIST,
}


def _crosses_midnight(train: TrainSummary) -> bool:
    if train.departure_time is None or train.duration_minutes is None:
        return False
    return (
        train.departure_time.hour * 60 + train.departure_time.minute + train.duration_minutes
        >= 1440
    )


def _probe_train(trains: list[TrainSummary]) -> TrainSummary:
    """Best train for the date-semantics probe (Q1).

    A non-daily train that starts at the boarding station and runs past midnight makes the two
    date hypotheses predict different valid dates; daily trains cannot discriminate them.
    """
    crossing = [t for t in trains if _crosses_midnight(t)]
    restricted = [
        t
        for t in crossing
        if t.running_days
        and t.running_days != "1111111"
        and t.origin_station_code == t.from_station_code
    ]
    restricted.sort(key=lambda t: (t.running_days or "").count("1"))
    return (restricted or crossing or trains)[0]


def _runs_on(running_days: str | None, day: date) -> bool | None:
    """Running days are Monday-first (verified 2026-11-14)."""
    if not running_days or len(running_days) != 7:
        return None
    return running_days[day.weekday()] == "1"


def _per_day(raw: Any, reference: date) -> list[dict[str, Any]]:
    days = []
    for entry in raw.get("availability", []) if isinstance(raw, dict) else []:
        if not isinstance(entry, dict):
            continue
        parsed = parse_railkit_date(entry.get("date"), reference=reference)
        status = reconcile_status_fields(
            ("rawStatus", entry.get("rawStatus")), ("status", entry.get("status"))
        ).parsed.status
        days.append(
            {
                "date": parsed.isoformat() if parsed else str(entry.get("date")),
                "raw_status": entry.get("rawStatus"),
                "status": status.value,
                "looks_running": status in RUNNING,
            }
        )
    return days


def _verdict(
    probes: dict[str, dict[str, Any]], running_days: str | None, later_day_offset: int
) -> str:
    """Which hypothesis explains which dates look like a real train run?"""
    observed = {
        d["date"]: d["looks_running"] for probe in probes.values() for d in probe.get("days", [])
    }
    if not observed or running_days in (None, "1111111"):
        return "INCONCLUSIVE (daily train or no data)"
    fits = {}
    for policy, shift in (("SEGMENT_BOARDING_DATE", later_day_offset), ("TRAIN_START_DATE", 0)):
        expected = {
            day: _runs_on(running_days, date.fromisoformat(day) - timedelta(days=shift))
            for day in observed
        }
        fits[policy] = all(expected[day] == observed[day] for day in observed)
    winners = [policy for policy, ok in fits.items() if ok]
    return winners[0] if len(winners) == 1 else f"INCONCLUSIVE ({fits})"


async def test_live_contract_walkthrough() -> None:
    settings = _settings()
    assert settings.railkit_api_key is not None
    secrets = settings.secret_values
    client = RailKitHttpClient(
        base_url=settings.railkit_base_url,
        api_key=settings.railkit_api_key.get_secret_value(),
        timeout=httpx.Timeout(20.0, connect=5.0),
        max_retries=0,
    )
    # One folder per run, so curated fixtures used by regression tests are never overwritten.
    folder = CAPTURE_ROOT / datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    journey = today_ist(SystemClock().now()) + timedelta(days=14)
    report: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "search": f"{SOURCE}->{DESTINATION}",
        "journey_date": journey.isoformat(),
    }
    try:
        # 1. Train search: auth, date format, station matching (Q2, Q3)
        raw_trains = await client.get_data(
            "train_search",
            f"/api/v1/trains/between/{SOURCE}/{DESTINATION}",
            params={"date": to_railkit_date(journey)},
        )
        _save(folder, "train_search", raw_trains, secrets)
        trains = map_train_search(raw_trains)
        assert trains, "no trains returned; try LIVE_SOURCE/LIVE_DESTINATION"
        report["trains_returned"] = len(trains)
        report["exact_station_matches"] = sum(
            (t.from_station_code, t.to_station_code) == (SOURCE, DESTINATION) for t in trains
        )
        train = _probe_train(trains)
        report["probe_train"] = {
            "train": train.train_number,
            "pair": f"{train.from_station_code}->{train.to_station_code}",
            "origin": train.origin_station_code,
            "running_days": train.running_days,
            "crosses_midnight": _crosses_midnight(train),
        }

        # 2. Route structure, ordering and day offsets (Q11)
        raw_info = await client.get_data("train_info", f"/api/v1/trains/{train.train_number}/info")
        _save(folder, f"train_info_{train.train_number}", raw_info, secrets)
        route = map_train_route(
            raw_info, train_number=train.train_number, fetched_at=datetime.now(UTC)
        )
        analysis = analyze_route(route)
        journey_route = validate_journey(analysis, train.from_station_code, train.to_station_code)
        report["route"] = {
            "stops": len(route.stops),
            "verified": journey_route.verified,
            "issues": [issue.value for issue in journey_route.issues],
        }
        assert journey_route.verified, journey_route.issues
        source_index = journey_route.source_index
        destination_index = journey_route.destination_index
        assert source_index is not None
        assert destination_index is not None

        classes = [
            c
            for c in (route.classes or ())
            if c in KNOWN_CLASS_CODES and c in settings.supported_classes
        ]
        travel_class = next((c for c in ("3A", "SL", "2A", "CC") if c in classes), "SL")
        report["travel_class"] = travel_class

        # 3. Direct availability (Q4-Q9)
        direct = AvailabilityQuery(
            train.train_number,
            train.from_station_code,
            train.to_station_code,
            journey,
            travel_class,
        )
        raw_direct = await client.get_data(
            "seat_availability",
            f"/api/v1/seats/{direct.train_number}/{direct.from_station}/{direct.to_station}/"
            f"{to_railkit_date(journey)}/{travel_class}/GN",
        )
        _save(folder, "seat_availability_direct", raw_direct, secrets)
        record = map_availability(raw_direct, direct, fare_currency=settings.railkit_fare_currency)
        report["direct"] = {
            "status": record.status.value,
            "raw_status": record.raw_status,
            "prediction": record.prediction.text if record.prediction else None,
            "can_book": record.can_book,
            "anomalies": list(record.anomalies),
            "days_returned": len(raw_direct.get("availability", [])),
        }

        # 4. Segment boarding after midnight: which date does RailKit expect? (Q1)
        source_day = departure_day(analysis, source_index)
        later = next(
            (
                i
                for i in journey_route.intermediate_indices
                if departure_day(analysis, i) > source_day
            ),
            None,
        )
        if later is None:
            report["Q1"] = "INCONCLUSIVE (no stop after midnight on the probe train)"
            return
        start = train_start_date(journey, analysis, source_index)
        boarding = provider_query_date(
            start, analysis, later, AvailabilityDatePolicy.SEGMENT_BOARDING_DATE
        )
        later_code = route.stops[later].station_code
        probes: dict[str, dict[str, Any]] = {}
        for label, sent in (("boarding_date", boarding), ("train_start_date", start)):
            probe: dict[str, Any] = {
                "segment": f"{later_code}->{train.to_station_code}",
                "sent": sent.isoformat(),
            }
            try:
                raw = await client.get_data(
                    "seat_availability",
                    f"/api/v1/seats/{train.train_number}/{later_code}/{train.to_station_code}/"
                    f"{to_railkit_date(sent)}/{travel_class}/GN",
                )
                _save(folder, f"seat_availability_after_midnight_{label}", raw, secrets)
                probe["days"] = _per_day(raw, sent)
            except ProviderError as error:
                probe["error"] = f"{error.category.value} {error.status_code}: {error.message}"
            probes[label] = probe
        report["Q1"] = {
            "later_stop": later_code,
            "later_stop_departure_day_offset": departure_day(analysis, later),
            "probes": probes,
            "verdict": _verdict(probes, train.running_days, departure_day(analysis, later)),
        }
    finally:
        await client.aclose()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        for key, value in report.items():
            _report(key, value)


def test_live_capture_folder_is_documented() -> None:
    """Keeps the capture location discoverable (no network)."""
    assert CAPTURE_ROOT.parent.joinpath("MANIFEST.md").exists()
    assert isinstance(date.today(), date)  # noqa: DTZ011
