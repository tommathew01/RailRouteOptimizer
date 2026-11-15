"""Simulated railway network for demo mode and tests.

Station codes/names are real public identifiers; **all trains are fictional** ("DEMO …", numbers
906xx) and every availability value is generated. Nothing here may be presented as live data.
Timetables are generated from distances so overnight runs cross midnight realistically
(including a midnight that falls during a halt).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from functools import cache

from app.domain.models import Station
from app.domain.time import MINUTES_PER_DAY

STATIONS: dict[str, Station] = {
    s.code: s
    for s in (
        Station("MAQ", "Mangaluru Central", "Mangaluru", 12.8641, 74.8429),
        Station("KGQ", "Kasaragod", "Kasaragod", 12.4925, 74.9886),
        Station("CAN", "Kannur", "Kannur", 11.8689, 75.3555),
        Station("TLY", "Thalassery", "Thalassery", 11.7540, 75.4930),
        Station("BDJ", "Vatakara", "Vatakara", 11.6000, 75.5900),
        Station("CLT", "Kozhikode Main", "Kozhikode", 11.2470, 75.7800),
        Station("TIR", "Tirur", "Tirur", 10.9150, 75.9220),
        Station("KTU", "Kuttippuram", "Kuttippuram", 10.8450, 76.0280),
        Station("SRR", "Shoranur Junction", "Shoranur", 10.7620, 76.2720),
        Station("OTP", "Ottappalam", "Ottappalam", 10.7710, 76.3770),
        Station("PGT", "Palakkad Junction", "Palakkad", 10.7980, 76.6390),
        Station("TCR", "Thrissur", "Thrissur", 10.5150, 76.2100),
        Station("AFK", "Angamaly", "Angamaly", 10.1850, 76.3700),
        Station("AWY", "Aluva", "Aluva", 10.1100, 76.3530),
        Station("ERS", "Ernakulam Junction", "Kochi", 9.9690, 76.2900),
        Station("ALLP", "Alappuzha", "Alappuzha", 9.4880, 76.3270),
        Station("KTYM", "Kottayam", "Kottayam", 9.5850, 76.5220),
        Station("CGY", "Changanassery", "Changanassery", 9.4440, 76.5410),
        Station("TRVL", "Tiruvalla", "Tiruvalla", 9.3820, 76.5740),
        Station("CNGR", "Chengannur", "Chengannur", 9.3180, 76.6110),
        Station("KYJ", "Kayamkulam Junction", "Kayamkulam", 9.1760, 76.5050),
        Station("QLN", "Kollam Junction", "Kollam", 8.8860, 76.5950),
        Station("VAK", "Varkala Sivagiri", "Varkala", 8.7360, 76.7080),
        Station("TVC", "Thiruvananthapuram Central", "Thiruvananthapuram", 8.4875, 76.9525),
        Station("CBE", "Coimbatore Junction", "Coimbatore", 10.9960, 76.9670),
        Station("TUP", "Tiruppur", "Tiruppur", 11.1080, 77.3400),
        Station("ED", "Erode Junction", "Erode", 11.3400, 77.7180),
        Station("SA", "Salem Junction", "Salem", 11.6710, 78.1110),
        Station("JTJ", "Jolarpettai Junction", "Jolarpettai", 12.5680, 78.5760),
        Station("KPD", "Katpadi Junction", "Vellore", 12.9720, 79.1370),
        Station("MAS", "MGR Chennai Central", "Chennai", 13.0827, 80.2750),
    )
}


@dataclass(frozen=True, slots=True)
class MockStop:
    code: str
    distance_km: int
    arrival: time | None
    departure: time | None
    day: int  # 1-based, RailKit style (day of arrival; origin = day of departure)
    halt_minutes: int


@dataclass(frozen=True, slots=True)
class MockTrain:
    number: str
    name: str
    stops: tuple[MockStop, ...]
    classes: tuple[str, ...]
    running_days: str = "1111111"

    def index_of(self, code: str) -> int | None:
        for index, stop in enumerate(self.stops):
            if stop.code == code:
                return index
        return None


def _clock(minutes: int) -> time:
    minutes %= MINUTES_PER_DAY
    return time(minutes // 60, minutes % 60)


def _build(
    number: str,
    name: str,
    classes: tuple[str, ...],
    start: time,
    speed_kmph: float,
    plan: list[tuple[str, int, int]],
) -> MockTrain:
    """``plan`` = [(station_code, cumulative_km, halt_minutes), ...]."""
    stops: list[MockStop] = []
    departure_abs = start.hour * 60 + start.minute
    previous_km = 0
    for index, (code, km, halt) in enumerate(plan):
        if index == 0:
            stops.append(MockStop(code, km, None, _clock(departure_abs), 1, 0))
            previous_km = km
            continue
        run = max(4, round((km - previous_km) / speed_kmph * 60))
        arrival_abs = departure_abs + run
        is_last = index == len(plan) - 1
        departure = None if is_last else _clock(arrival_abs + halt)
        stops.append(
            MockStop(
                code,
                km,
                _clock(arrival_abs),
                departure,
                arrival_abs // MINUTES_PER_DAY + 1,
                0 if is_last else halt,
            )
        )
        departure_abs = arrival_abs + halt
        previous_km = km
    return MockTrain(number, name, tuple(stops), classes)


_COASTAL = [
    ("MAQ", 0, 0), ("KGQ", 46, 2), ("CAN", 132, 5), ("TLY", 153, 2), ("BDJ", 180, 2),
    ("CLT", 225, 10), ("TIR", 266, 2), ("KTU", 280, 1), ("SRR", 311, 10), ("TCR", 344, 3),
    ("AFK", 384, 1), ("AWY", 397, 3), ("ERS", 418, 10), ("KTYM", 482, 3), ("CGY", 500, 1),
    ("TRVL", 508, 1), ("CNGR", 517, 1), ("KYJ", 541, 2), ("QLN", 576, 5), ("VAK", 602, 1),
    ("TVC", 641, 0),
]  # fmt: skip

_NIGHT_MAIL = [
    ("CLT", 0, 0), ("TIR", 41, 2), ("SRR", 86, 10), ("TCR", 119, 3), ("AWY", 172, 2),
    ("ERS", 193, 10), ("ALLP", 250, 3), ("KYJ", 294, 2), ("QLN", 329, 5), ("TVC", 394, 0),
]  # fmt: skip

_INTERCITY = [
    ("TCR", 0, 0), ("AWY", 53, 2), ("ERS", 74, 5), ("KTYM", 138, 3), ("KYJ", 197, 2),
    ("QLN", 232, 3), ("TVC", 297, 0),
]  # fmt: skip

_PENINSULAR = [
    ("MAS", 0, 0), ("KPD", 129, 5), ("JTJ", 213, 3), ("SA", 334, 5), ("ED", 394, 5),
    ("TUP", 444, 2), ("CBE", 494, 5), ("PGT", 548, 5), ("OTP", 580, 1), ("SRR", 601, 10),
    ("TCR", 634, 3), ("AWY", 687, 2), ("ERS", 708, 10), ("KTYM", 772, 3), ("CNGR", 807, 1),
    ("KYJ", 831, 2), ("QLN", 866, 5), ("TVC", 931, 0),
]  # fmt: skip


def _reverse(plan: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    total = plan[-1][1]
    halts = [halt for _, _, halt in plan]
    return [
        (code, total - km, halts[len(plan) - 1 - i] if 0 < i < len(plan) - 1 else 0)
        for i, (code, km, _) in enumerate(reversed(plan))
    ]


@cache
def demo_trains() -> dict[str, MockTrain]:
    trains = (
        _build("90601", "DEMO COASTAL EXPRESS", ("2A", "3A", "SL"), time(16, 35), 52, _COASTAL),
        _build(
            "90602",
            "DEMO COASTAL EXPRESS",
            ("2A", "3A", "SL"),
            time(17, 50),
            52,
            _reverse(_COASTAL),
        ),
        _build("90603", "DEMO NIGHT MAIL", ("1A", "2A", "3A", "SL"), time(22, 30), 48, _NIGHT_MAIL),
        _build("90605", "DEMO INTERCITY", ("CC", "2S"), time(6, 0), 58, _INTERCITY),
        _build(
            "90607",
            "DEMO PENINSULAR EXPRESS",
            ("1A", "2A", "3A", "SL"),
            time(15, 10),
            56,
            _PENINSULAR,
        ),
    )
    return {train.number: train for train in trains}


#: Fixed demo situations so the showcase search (TIR → TVC) always tells a clear story:
#: the direct ticket is waitlisted, but split tickets on the same train are available.
DEMO_OVERRIDES: dict[tuple[str, str, str, str], tuple[str, str | None, int | None]] = {
    ("90601", "TIR", "TVC", "3A"): ("GNWL42/WL27", "38% Chance", 38),
    ("90601", "TIR", "TVC", "SL"): ("GNWL118/WL86", "12% Chance", 12),
    ("90601", "TIR", "TVC", "2A"): ("RAC 6", "91% Chance", 91),
    ("90601", "TIR", "ERS", "3A"): ("AVAILABLE-0007", None, None),
    ("90601", "ERS", "TVC", "3A"): ("AVAILABLE-0031", None, None),
    ("90601", "TIR", "SRR", "SL"): ("AVAILABLE-0044", None, None),
    ("90601", "SRR", "KTYM", "SL"): ("AVAILABLE-0012", None, None),
    ("90601", "KTYM", "TVC", "SL"): ("AVAILABLE-0058", None, None),
    ("90603", "TIR", "TVC", "3A"): ("REGRET/WL", None, None),
}

CLASS_BIAS = {"1A": -0.12, "2A": -0.05, "3A": 0.08, "3E": 0.05, "SL": 0.12, "CC": -0.02, "EC": -0.1}
CLASS_BIAS |= {"2S": 0.0}
FARE_RATE = {"1A": (3.4, 60), "2A": (2.05, 50), "3A": (1.45, 40), "3E": (1.3, 40)}
FARE_RATE |= {"SL": (0.55, 20), "CC": (1.15, 40), "EC": (2.4, 60), "2S": (0.33, 15)}
