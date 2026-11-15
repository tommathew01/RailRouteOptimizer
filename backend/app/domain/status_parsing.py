"""Indian Railways availability-status vocabulary → normalized status (doc 03 §6).

Explicit patterns only: anything not recognized is ``UNKNOWN``. Prediction text is never parsed
here. The exact provider string is always preserved by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.enums import AvailabilityStatus

WAITLIST_TYPES = (
    "GNWL", "RLWL", "PQWL", "RQWL", "RSWL", "TQWL", "NPWL", "CKWL", "PTWL",
    "LDWL", "SSWL", "DFWL", "HPWL", "DPWL", "FTWL", "YUWL", "LBWL", "WL",
)  # fmt: skip

_WS = re.compile(r"\s+")
_CONFIRMED = re.compile(r"^(?:CNF|CONFIRMED|CONFIRM)(?:\b|/|$)")
_AVAILABLE = re.compile(r"^(?:CURR_AVBL|AVAILABLE|AVBL|AVL)(?:[\s#:\-]*0*(\d+))?\s*$")
_RAC = re.compile(r"^RAC(?:[\s#:\-]*0*(\d+))?(?:\s*/\s*(?:RAC)?[\s#:\-]*0*(\d+))?\s*$")
_WAITLIST = re.compile(
    r"^(" + "|".join(WAITLIST_TYPES) + r")(?:[\s#:\-]*0*(\d+))?"
    r"(?:\s*/\s*(?:" + "|".join(WAITLIST_TYPES) + r")?[\s#:\-]*0*(\d+))?\s*$"
)
_RAILKIT_WAITLIST_WORDS = re.compile(r"^(?:WAITLIST|WAITLISTED|WAITING(?:\s+LIST)?)$")
_NOT_AVAILABLE = re.compile(
    r"^(?:REGRET(?:\s*/\s*WL)?|NOT[\s_\-]?AVAILABLE|NO[\s_\-]?SEATS?(?:\s+AVAILABLE)?|"
    r"NOAVL|BOOKING\s+CLOSED|CLOSED|TRAIN\s+DEPARTED|DEPARTED|TRAIN\s+CANCELL?ED|"
    r"CHART(?:ING)?\s+(?:PREPARED|DONE)|CLASS\s+NOT\s+(?:EXIST|AVAILABLE))\b"
)
_UNKNOWN_WORD = re.compile(r"^UNKNOWN$")


@dataclass(frozen=True, slots=True)
class ParsedStatus:
    status: AvailabilityStatus
    recognized: bool
    waitlist_type: str | None = None
    waitlist_number: int | None = None
    rac_number: int | None = None
    available_count: int | None = None
    anomaly: str | None = None


UNRECOGNIZED = ParsedStatus(AvailabilityStatus.UNKNOWN, recognized=False)


def _normalize(text: str) -> str:
    return _WS.sub(" ", text.strip().upper())


def parse_status_text(text: object) -> ParsedStatus:
    """Parse one provider status string (e.g. ``"RLWL31/WL23"``, ``"AVAILABLE-0012"``)."""
    if not isinstance(text, str) or not text.strip():
        return UNRECOGNIZED
    value = _normalize(text)

    if _NOT_AVAILABLE.match(value):
        return ParsedStatus(AvailabilityStatus.NOT_AVAILABLE, recognized=True)
    if _CONFIRMED.match(value):
        return ParsedStatus(AvailabilityStatus.CONFIRMED, recognized=True)
    if match := _AVAILABLE.match(value):
        count = int(match.group(1)) if match.group(1) else None
        if count == 0:
            # "Available, zero seats" is self-contradictory: never guess.
            return ParsedStatus(
                AvailabilityStatus.UNKNOWN, recognized=False, anomaly="AVAILABLE_WITH_ZERO_COUNT"
            )
        return ParsedStatus(AvailabilityStatus.AVAILABLE, recognized=True, available_count=count)
    if match := _RAC.match(value):
        number_text = match.group(2) or match.group(1)
        number = int(number_text) if number_text else None
        return ParsedStatus(AvailabilityStatus.RAC, recognized=True, rac_number=number)
    if match := _WAITLIST.match(value):
        wl_type, first, current = match.group(1), match.group(2), match.group(3)
        # "RLWL31/WL23": the trailing number is the current position; keep the specific type.
        number_text = current or first
        return ParsedStatus(
            AvailabilityStatus.WAITLIST,
            recognized=True,
            waitlist_type=wl_type,
            waitlist_number=int(number_text) if number_text else None,
        )
    if _RAILKIT_WAITLIST_WORDS.match(value):
        return ParsedStatus(AvailabilityStatus.WAITLIST, recognized=True)
    if _UNKNOWN_WORD.match(value):
        return UNRECOGNIZED
    return UNRECOGNIZED


#: Statuses that may legitimately be reported differently by two fields of one response.
_COMPATIBLE = {
    frozenset({AvailabilityStatus.AVAILABLE, AvailabilityStatus.CONFIRMED}),
}


@dataclass(frozen=True, slots=True)
class ReconciledStatus:
    parsed: ParsedStatus
    anomalies: tuple[str, ...]


def reconcile_status_fields(*candidates: tuple[str, object]) -> ReconciledStatus:
    """Combine several status fields of one response, most specific first.

    Every recognized field must agree (or be in a compatible group); otherwise the result is
    ``UNKNOWN`` with a ``STATUS_FIELDS_CONFLICT`` anomaly. The first recognized field supplies the
    detail (waitlist type/number, counts), so pass the raw provider string first.
    """
    anomalies: list[str] = []
    recognized: list[tuple[str, ParsedStatus]] = []
    for name, text in candidates:
        parsed = parse_status_text(text)
        if parsed.anomaly:
            anomalies.append(f"{parsed.anomaly}:{name}")
        if parsed.recognized:
            recognized.append((name, parsed))
        elif isinstance(text, str) and text.strip() and not parsed.anomaly:
            anomalies.append(f"UNRECOGNIZED_STATUS:{name}")

    if not recognized:
        return ReconciledStatus(UNRECOGNIZED, tuple(anomalies))

    statuses = {parsed.status for _, parsed in recognized}
    if len(statuses) > 1 and frozenset(statuses) not in _COMPATIBLE:
        anomalies.append("STATUS_FIELDS_CONFLICT:" + ",".join(name for name, _ in recognized))
        return ReconciledStatus(UNRECOGNIZED, tuple(anomalies))

    primary = recognized[0][1]
    # Fill numeric detail from a later field when the primary did not carry it.
    detail = {
        "waitlist_number": primary.waitlist_number,
        "rac_number": primary.rac_number,
        "available_count": primary.available_count,
    }
    for _, parsed in recognized[1:]:
        if parsed.status is primary.status:
            for key in detail:
                if detail[key] is None:
                    detail[key] = getattr(parsed, key)
    merged = ParsedStatus(
        primary.status,
        recognized=True,
        waitlist_type=primary.waitlist_type,
        waitlist_number=detail["waitlist_number"],
        rac_number=detail["rac_number"],
        available_count=detail["available_count"],
    )
    return ReconciledStatus(merged, tuple(anomalies))
