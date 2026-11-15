from __future__ import annotations

import pytest

from app.domain.enums import AvailabilityStatus as S
from app.domain.status_parsing import parse_status_text, reconcile_status_fields


@pytest.mark.parametrize(
    ("text", "status", "details"),
    [
        ("CNF", S.CONFIRMED, {}),
        ("Confirmed", S.CONFIRMED, {}),
        ("CNF/B1/23", S.CONFIRMED, {}),
        ("AVAILABLE-0012", S.AVAILABLE, {"available_count": 12}),
        ("AVAILABLE", S.AVAILABLE, {"available_count": None}),
        ("AVL 45", S.AVAILABLE, {"available_count": 45}),
        ("CURR_AVBL-0007", S.AVAILABLE, {"available_count": 7}),
        ("RAC 2", S.RAC, {"rac_number": 2}),
        ("RAC12/RAC5", S.RAC, {"rac_number": 5}),
        ("RAC", S.RAC, {"rac_number": None}),
        ("GNWL45/WL30", S.WAITLIST, {"waitlist_type": "GNWL", "waitlist_number": 30}),
        ("RLWL31/WL23", S.WAITLIST, {"waitlist_type": "RLWL", "waitlist_number": 23}),
        ("PQWL5", S.WAITLIST, {"waitlist_type": "PQWL", "waitlist_number": 5}),
        ("TQWL 12", S.WAITLIST, {"waitlist_type": "TQWL", "waitlist_number": 12}),
        ("WL 23", S.WAITLIST, {"waitlist_type": "WL", "waitlist_number": 23}),
        ("WAITLIST", S.WAITLIST, {}),
        ("REGRET/WL", S.NOT_AVAILABLE, {}),
        ("REGRET", S.NOT_AVAILABLE, {}),
        ("NOT AVAILABLE", S.NOT_AVAILABLE, {}),
        ("not_available", S.NOT_AVAILABLE, {}),
        ("TRAIN DEPARTED", S.NOT_AVAILABLE, {}),
        ("TRAIN CANCELLED", S.NOT_AVAILABLE, {}),
        ("CLASS NOT EXIST", S.NOT_AVAILABLE, {}),
        ("Booking Closed", S.NOT_AVAILABLE, {}),
    ],
)
def test_known_vocabulary(text: str, status: S, details: dict[str, object]) -> None:
    parsed = parse_status_text(text)
    assert parsed.recognized
    assert parsed.status is status
    for key, value in details.items():
        assert getattr(parsed, key) == value


@pytest.mark.parametrize(
    "text", [None, "", "   ", "N/A", "NA", "???", "UNKNOWN", 42, "WL-ish maybe", "75% Chance"]
)
def test_anything_else_is_unknown_never_unavailable(text: object) -> None:
    parsed = parse_status_text(text)
    assert parsed.status is S.UNKNOWN
    assert not parsed.recognized


def test_available_with_zero_count_is_contradictory_and_unknown() -> None:
    parsed = parse_status_text("AVAILABLE-0000")
    assert parsed.status is S.UNKNOWN
    assert parsed.anomaly == "AVAILABLE_WITH_ZERO_COUNT"


def test_reconcile_uses_raw_status_for_detail_when_fields_agree() -> None:
    result = reconcile_status_fields(
        ("rawStatus", "RLWL31/WL23"), ("availabilityText", "WL 23"), ("status", "WAITLIST")
    )
    assert result.parsed.status is S.WAITLIST
    assert result.parsed.waitlist_type == "RLWL"
    assert result.parsed.waitlist_number == 23
    assert result.anomalies == ()


def test_reconcile_conflict_is_unknown_with_anomaly() -> None:
    result = reconcile_status_fields(("rawStatus", "GNWL5/WL3"), ("status", "AVAILABLE"))
    assert result.parsed.status is S.UNKNOWN
    assert any(a.startswith("STATUS_FIELDS_CONFLICT") for a in result.anomalies)


def test_reconcile_available_and_confirmed_are_compatible() -> None:
    result = reconcile_status_fields(("rawStatus", "AVAILABLE-0010"), ("status", "CONFIRMED"))
    assert result.parsed.status is S.AVAILABLE  # raw wins; the two are not collapsed
    assert result.parsed.available_count == 10


def test_reconcile_fills_missing_detail_from_later_field() -> None:
    result = reconcile_status_fields(("rawStatus", "WAITLIST"), ("availabilityText", "WL 9"))
    assert result.parsed.waitlist_number == 9


def test_reconcile_records_unrecognized_fields() -> None:
    result = reconcile_status_fields(("rawStatus", "SOMETHING NEW"), ("status", "WAITLIST"))
    assert result.parsed.status is S.WAITLIST
    assert "UNRECOGNIZED_STATUS:rawStatus" in result.anomalies


def test_reconcile_nothing_recognized() -> None:
    result = reconcile_status_fields(("rawStatus", None), ("status", ""))
    assert result.parsed.status is S.UNKNOWN
