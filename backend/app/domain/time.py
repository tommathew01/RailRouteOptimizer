"""Railway time helpers. Journey dates and displayed times are Asia/Kolkata (README)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MINUTES_PER_DAY = 24 * 60


def today_ist(now_utc: datetime) -> date:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    return now_utc.astimezone(IST).date()


def ist_datetime(day: date, wall_clock: time, extra_minutes: int = 0) -> datetime:
    """Combine a calendar date and an IST wall-clock time, then add minutes."""
    return datetime.combine(day, wall_clock, tzinfo=IST) + timedelta(minutes=extra_minutes)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def minutes_of_day(value: time) -> int:
    return value.hour * 60 + value.minute
