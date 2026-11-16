"""IRCTC maintenance window 23:45-00:20 IST (docs/08 D-31): boundaries, midnight, timezones."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, timezone

import pytest

from app.domain.maintenance import MaintenanceWindow
from app.domain.time import IST

WINDOW = MaintenanceWindow(time(23, 45), time(0, 20))


def ist(day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=IST)


@pytest.mark.parametrize(
    ("moment", "active"),
    [
        (ist(16, 23, 44, 59), False),
        (ist(16, 23, 45), True),  # start is inclusive
        (ist(16, 23, 59, 59), True),
        (ist(17, 0, 0), True),  # across midnight
        (ist(17, 0, 19, 59), True),
        (ist(17, 0, 20), False),  # end is exclusive: open again at 12:20 AM
        (ist(17, 12, 0), False),
    ],
)
def test_window_boundaries_in_ist(moment: datetime, active: bool) -> None:
    assert WINDOW.active(moment) is active


@pytest.mark.parametrize(
    "zone",
    [UTC, timezone(timedelta(hours=-8)), timezone(timedelta(hours=9)), timezone(timedelta(0))],
)
def test_the_same_instant_gives_the_same_answer_in_every_timezone(zone: timezone) -> None:
    inside = ist(16, 23, 50).astimezone(zone)  # 18:20 UTC, 10:20 in UTC-8, 03:20 next day UTC+9
    outside = ist(17, 0, 25).astimezone(zone)
    assert WINDOW.active(inside)
    assert not WINDOW.active(outside)


def test_window_end_is_tomorrow_before_midnight_and_today_after() -> None:
    assert WINDOW.ends_at(ist(16, 23, 50)) == ist(17, 0, 20)
    assert WINDOW.ends_at(ist(17, 0, 5)) == ist(17, 0, 20)
    assert WINDOW.ends_at(ist(17, 9, 0)) is None


def test_naive_instants_and_empty_windows_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        WINDOW.active(datetime(2026, 11, 16, 23, 50))  # noqa: DTZ001 (deliberately naive)
    with pytest.raises(ValueError, match="must differ"):
        MaintenanceWindow(time(1, 0), time(1, 0))


def test_message_names_the_window_in_ist() -> None:
    assert "between 11:45 PM and 12:20 AM IST" in WINDOW.describe()
    assert MaintenanceWindow(time(1, 0), time(2, 30)).active(ist(16, 2, 0))
