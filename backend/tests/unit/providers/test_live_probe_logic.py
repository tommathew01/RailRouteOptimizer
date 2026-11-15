"""Offline checks of the live Q1 date-semantics probe (tests/live), which decides a setting."""

from __future__ import annotations

from datetime import date, time, timedelta

from app.domain.models import TrainSummary
from tests.live.test_railkit_live import _probe_train, _verdict

SATURDAY_ONLY = "0000010"  # Monday-first


def _days(start: date, running: set[date]) -> list[dict[str, object]]:
    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "looks_running": start + timedelta(days=i) in running,
        }
        for i in range(4)
    ]


def test_verdict_identifies_boarding_date_semantics() -> None:
    sat, sun = date(2026, 11, 28), date(2026, 11, 29)
    # The Saturday-only train reaches the after-midnight stop on Sunday.
    probes = {
        "boarding_date": {"days": _days(sun, {sun})},
        "train_start_date": {"days": _days(sat, {sun})},
    }
    assert _verdict(probes, SATURDAY_ONLY, later_day_offset=1) == "SEGMENT_BOARDING_DATE"


def test_verdict_identifies_train_start_date_semantics() -> None:
    sat, sun = date(2026, 11, 28), date(2026, 11, 29)
    probes = {
        "boarding_date": {"days": _days(sun, set())},
        "train_start_date": {"days": _days(sat, {sat})},
    }
    assert _verdict(probes, SATURDAY_ONLY, later_day_offset=1) == "TRAIN_START_DATE"


def test_verdict_refuses_to_guess() -> None:
    sat = date(2026, 11, 28)
    assert _verdict({"x": {"days": _days(sat, {sat})}}, "1111111", 1).startswith("INCONCLUSIVE")
    everything = {"x": {"days": _days(sat, {sat + timedelta(days=i) for i in range(4)})}}
    assert _verdict(everything, SATURDAY_ONLY, 1).startswith("INCONCLUSIVE")
    assert _verdict({"x": {"error": "PROVIDER_REJECTED"}}, SATURDAY_ONLY, 1).startswith(
        "INCONCLUSIVE"
    )


def test_probe_prefers_non_daily_overnight_train_starting_at_boarding_station() -> None:
    def t(number: str, days: str, dep: time, minutes: int, origin: str) -> TrainSummary:
        return TrainSummary(
            number,
            None,
            "NZM",
            "BDTS",
            origin_station_code=origin,
            departure_time=dep,
            duration_minutes=minutes,
            running_days=days,
        )

    trains = [
        t("12904", "1111111", time(4, 0), 1195, "ASR"),  # same-day, daily
        t("12472", "0110110", time(21, 40), 1110, "SVDK"),  # starts elsewhere
        t("22210", "0100010", time(22, 15), 1055, "NZM"),
        t("12248", "0000010", time(16, 30), 1005, "NZM"),  # most restrictive → chosen
    ]
    assert _probe_train(trains).train_number == "12248"
    assert _probe_train(trains[:1]).train_number == "12904"  # nothing better: first train
