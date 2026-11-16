"""Daily railway maintenance window (docs/08 D-31). Standard library only.

IRCTC does not allow train searches or seat-availability checks between 23:45 and 00:20 IST.
The window is an IST wall-clock interval that may cross midnight; it is evaluated on a
timezone-aware instant, so the server's (or the user's) timezone never matters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.domain.time import IST


def _clock_text(value: time) -> str:
    """12-hour IST time as IRCTC writes it, e.g. 11:45 PM, 12:20 AM."""
    hour = value.hour % 12 or 12
    return f"{hour}:{value.minute:02d} {'AM' if value.hour < 12 else 'PM'}"


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    #: IST wall-clock times; ``starts`` is inclusive, ``ends`` exclusive (12:20 AM is open again).
    starts: time
    ends: time

    def __post_init__(self) -> None:
        if self.starts == self.ends:
            raise ValueError("maintenance window start and end must differ")
        if self.starts.tzinfo is not None or self.ends.tzinfo is not None:
            raise ValueError("maintenance window times are IST wall-clock times")

    def _wall_clock(self, now: datetime) -> time:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return now.astimezone(IST).time()

    def active(self, now: datetime) -> bool:
        t = self._wall_clock(now)
        if self.starts < self.ends:
            return self.starts <= t < self.ends
        return t >= self.starts or t < self.ends  # crosses midnight (23:45 → 00:20)

    def ends_at(self, now: datetime) -> datetime | None:
        """When the window that is active at ``now`` closes (IST); ``None`` when not active."""
        if not self.active(now):
            return None
        local = now.astimezone(IST)
        day = local.date()
        if local.time() >= self.ends:  # still the evening part: it ends tomorrow
            day += timedelta(days=1)
        return datetime.combine(day, self.ends, tzinfo=IST)

    def describe(self) -> str:
        return (
            "IRCTC does not allow train searches or seat availability checks between "
            f"{_clock_text(self.starts)} and {_clock_text(self.ends)} IST (daily maintenance). "
            "Searching works again automatically after the window ends; results you already "
            "have stay available."
        )

    @property
    def starts_text(self) -> str:
        return _clock_text(self.starts)

    @property
    def ends_text(self) -> str:
        return _clock_text(self.ends)
