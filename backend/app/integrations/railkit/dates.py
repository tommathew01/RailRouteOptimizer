"""The single place where RailKit date formats are produced and parsed (doc 07 §3)."""

from __future__ import annotations

from datetime import date, datetime, time

_FULL_FORMATS = ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%a, %d %b %Y")
_YEARLESS_FORMATS = ("%d-%b", "%d %b", "%a, %d %b")


def to_railkit_date(value: date) -> str:
    """RailKit path/query dates are ``DD-MM-YYYY``."""
    return value.strftime("%d-%m-%Y")


def parse_railkit_date(text: object, *, reference: date | None = None) -> date | None:
    """Parse a date echoed by RailKit (docs show ``"1-9-2026"``). Returns ``None`` if unsure.

    A year-less value (``"1 Sep"``) is accepted only with a ``reference`` date and resolves to the
    year that puts it closest to the reference.
    """
    if not isinstance(text, str):
        return None
    value = " ".join(text.strip().split())
    if not value:
        return None
    for fmt in _FULL_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()  # noqa: DTZ007 (date only)
        except ValueError:
            continue
    if reference is None:
        return None
    for fmt in _YEARLESS_FORMATS:
        try:
            parsed = datetime.strptime(f"{value} {reference.year}", f"{fmt} %Y").date()  # noqa: DTZ007
        except ValueError:
            continue
        candidates = [parsed.replace(year=reference.year + delta) for delta in (-1, 0, 1)]
        return min(candidates, key=lambda c: abs((c - reference).days))
    return None


def parse_clock_time(text: object) -> time | None:
    """``"16:05"`` → 16:05. ``"--"``, ``"SRC"``, ``"DSTN"`` and anything malformed → ``None``."""
    if not isinstance(text, str):
        return None
    value = text.strip()
    parts = value.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    hours, minutes = int(parts[0]), int(parts[1])
    if 0 <= hours <= 23 and 0 <= minutes <= 59:
        return time(hours, minutes)
    return None
