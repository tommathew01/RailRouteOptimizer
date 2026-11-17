"""Dominated split-ticket combinations (docs/08 D-34): results and provider requests.

A path is dominated when a run of two or more of its segments is covered by one segment that is
CONFIRMED/AVAILABLE for the same train run, class and quota. Dominated paths are never returned
and their remaining segments are never requested.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from app.domain.enums import AvailabilityStatus as Status
from app.domain.enums import Quota
from app.domain.models import SegmentObservation
from app.optimization.dominance import dominating_run, is_dominated, last_stop_dominated
from app.optimization.graph import build_graph
from app.optimization.paths import find_paths
from app.optimization.planner import ComboSpec, ComboState, PlannedQuery, QueryPlanner
from app.optimization.policy import SearchFilters
from app.optimization.ranking import rank_paths
from tests.unit.optimization.builders import S, key, obs

WL_OK = SearchFilters(allow_rac=True, allow_waitlist=True)
Edge = tuple[int, int]


def paths_of(
    route: tuple[str, ...],
    *observations: SegmentObservation,
    cls: str = "3A",
    quota: Quota = Quota.GENERAL,
    filters: SearchFilters = WL_OK,
) -> list[tuple[str, ...]]:
    index = {code: i for i, code in enumerate(route)}
    graph = build_graph(key(cls=cls, quota=quota), observations, index, filters)
    return [p.stations for p in find_paths(graph, 0, len(route) - 1, max_paths=1_000)]


def drive(
    specs: list[ComboSpec],
    oracle: Callable[[PlannedQuery], Status],
    filters: SearchFilters = WL_OK,
    budget: int = 10_000,
) -> tuple[QueryPlanner, list[PlannedQuery]]:
    planner = QueryPlanner(specs, filters=filters)
    executed: list[PlannedQuery] = []
    while not planner.finished and len(executed) < budget:
        wave = planner.next_wave(min(8, budget - len(executed)))
        if not wave:
            break
        for query in wave:
            executed.append(query)
            planner.record(query, oracle(query))
    planner.stop()
    return planner, executed


def table(statuses: Mapping[Edge, Status], default: Status = S.NOT_AVAILABLE):
    return lambda q: statuses.get(q.edge, default)


# --- The rule itself ----------------------------------------------------------------------------
def test_rule_finds_the_longest_available_run_and_ignores_single_segments() -> None:
    available = {(0, 3), (1, 3)}.__contains__

    def lookup(a: int, b: int) -> bool:
        return available((a, b))

    assert dominating_run((0, 1, 2, 3, 4), lookup) == (0, 3)
    assert is_dominated((0, 1, 3, 4), lookup)  # 0→1→3 is covered by 0→3
    assert not is_dominated((0, 3, 4), lookup)  # 0→3 is itself the single segment
    assert not is_dominated((0, 2, 4), lookup)
    assert last_stop_dominated((0, 1, 2, 3), lookup)
    assert not last_stop_dominated((0, 1, 2), lookup)


# --- Test 1 / 2: direct available segment vs not available ------------------------------------
ROUTE = ("A", "B", "C", "D", "Z")


def test_1_available_segment_dominates_its_subdivisions() -> None:
    found = paths_of(
        ROUTE,
        obs("A", "D", S.AVAILABLE),
        obs("A", "B", S.AVAILABLE),
        obs("B", "D", S.AVAILABLE),
        obs("D", "Z", S.WAITLIST),
    )
    assert ("A", "D", "Z") in found
    assert ("A", "B", "D", "Z") not in found


def test_2_subdivisions_stay_when_the_longer_segment_is_waitlisted() -> None:
    found = paths_of(
        ROUTE,
        obs("A", "D", S.WAITLIST),
        obs("A", "B", S.AVAILABLE),
        obs("B", "D", S.AVAILABLE),
        obs("D", "Z", S.WAITLIST),
    )
    assert ("A", "B", "D", "Z") in found
    assert ("A", "D", "Z") in found  # both stay: different statuses and predictions


def test_rac_never_dominates() -> None:
    found = paths_of(
        ROUTE,
        obs("A", "D", S.RAC),
        obs("A", "B", S.AVAILABLE),
        obs("B", "D", S.AVAILABLE),
        obs("D", "Z", S.WAITLIST),
    )
    assert {("A", "D", "Z"), ("A", "B", "D", "Z")} <= set(found)


# --- Test 3 / 4: class and quota are separate search spaces -----------------------------------
def test_3_availability_in_one_class_never_prunes_another_class() -> None:
    sl = paths_of(
        ROUTE, obs("A", "D", S.AVAILABLE, cls="SL"), obs("D", "Z", S.WAITLIST, cls="SL"), cls="SL"
    )
    three_a = paths_of(
        ROUTE,
        obs("A", "B", S.AVAILABLE),
        obs("B", "D", S.AVAILABLE),
        obs("D", "Z", S.WAITLIST),
        cls="3A",
    )
    assert sl == [("A", "D", "Z")]
    assert three_a == [("A", "B", "D", "Z")]

    # Planner: two combinations (SL = 0, 3A = 1) on the same stops A=0 … Z=4.
    sl_status = {(0, 3): S.AVAILABLE, (0, 1): S.AVAILABLE, (3, 4): S.WAITLIST}
    a3_status = {(0, 1): S.AVAILABLE, (1, 3): S.AVAILABLE, (3, 4): S.WAITLIST}
    specs = [ComboSpec(c, 0, 4, (1, 2, 3)) for c in (0, 1)]
    _, executed = drive(
        specs, lambda q: (sl_status if q.combo_id == 0 else a3_status).get(q.edge, S.NOT_AVAILABLE)
    )
    assert (1, (1, 3)) in {(q.combo_id, q.edge) for q in executed}  # 3A still asks B→D
    assert (0, (1, 3)) not in {(q.combo_id, q.edge) for q in executed}  # SL does not


def test_4_availability_in_one_quota_never_prunes_another_quota() -> None:
    general = paths_of(
        ROUTE,
        obs("A", "D", S.AVAILABLE, quota=Quota.GENERAL),
        obs("D", "Z", S.WAITLIST, quota=Quota.GENERAL),
        quota=Quota.GENERAL,
    )
    tatkal = paths_of(
        ROUTE,
        obs("A", "B", S.AVAILABLE, quota=Quota.TATKAL),
        obs("B", "D", S.AVAILABLE, quota=Quota.TATKAL),
        obs("D", "Z", S.WAITLIST, quota=Quota.TATKAL),
        quota=Quota.TATKAL,
    )
    assert general == [("A", "D", "Z")]
    assert tatkal == [("A", "B", "D", "Z")]


# --- Test 5: overlapping available segments ----------------------------------------------------
def test_5_overlapping_available_segments_keep_different_coverage() -> None:
    route = ("A", "B", "C", "D", "E", "F")
    found = paths_of(
        route,
        obs("A", "D", S.AVAILABLE),
        obs("B", "E", S.AVAILABLE),
        obs("D", "F", S.WAITLIST),
        obs("E", "F", S.WAITLIST),
        obs("A", "B", S.AVAILABLE),
        obs("B", "D", S.AVAILABLE),  # makes A→B→D→F, which A→D dominates
        obs("D", "E", S.AVAILABLE),
    )
    assert ("A", "D", "F") in found
    assert ("A", "B", "E", "F") in found  # via B→E and the other waitlist E→F: kept
    assert ("A", "D", "E", "F") in found  # D→F is waitlisted, so D→E→F is not dominated
    assert ("A", "B", "D", "F") not in found  # A→B→D is covered by available A→D
    assert ("A", "B", "D", "E", "F") not in found
    for path in found:  # nothing returned is dominated
        idx = [route.index(code) for code in path]
        assert not any(
            (path[i], path[j]) in {("A", "D"), ("B", "E"), ("A", "B"), ("B", "D"), ("D", "E")}
            for i in range(len(idx))
            for j in range(i + 2, len(idx))
        )


# --- Test 6: the two screenshots ---------------------------------------------------------------
VIVEK = ("DBRG", "MXN", "NCB", "CAPE")  # 22504 VIVEK EXPRESS, SL, GN, 27 Nov
NZM_TVC = ("NZM", "MTJ", "BTE", "SRR")  # 22634 NZM TVC SF EXP, SL, GN, 27 Nov


def test_6_vivek_express_three_ticket_split_disappears() -> None:
    observations = [
        obs("DBRG", "NCB", S.AVAILABLE, cls="SL", pct=100, fare="505"),  # AVL 25
        obs("NCB", "CAPE", S.WAITLIST, cls="SL", pct=59, fare="1120"),  # RLWL35/WL24
        obs("DBRG", "MXN", S.AVAILABLE, cls="SL", pct=100, fare="180"),  # AVL 132
        obs("MXN", "NCB", S.AVAILABLE, cls="SL", pct=100, fare="430"),  # AVL 25
    ]
    found = paths_of(VIVEK, *observations, cls="SL")
    assert found == [("DBRG", "NCB", "CAPE")]  # Option 2 stays; Option 3 is gone
    graph = build_graph(key(cls="SL"), observations, {c: i for i, c in enumerate(VIVEK)}, WL_OK)
    [best] = rank_paths([(key(cls="SL"), p) for p in find_paths(graph, 0, 3)])
    assert best.fare.total is not None
    assert str(best.fare.total) == "1625"
    assert best.prediction_floor == 59


def test_6_nzm_tvc_three_ticket_split_disappears() -> None:
    found = paths_of(
        NZM_TVC,
        obs("NZM", "BTE", S.AVAILABLE, cls="SL", pct=100, fare="180"),  # AVL 13
        obs("BTE", "SRR", S.WAITLIST, cls="SL", pct=47, fare="995"),  # GNWL189/WL122
        obs("NZM", "MTJ", S.AVAILABLE, cls="SL", pct=100, fare="180"),
        obs("MTJ", "BTE", S.AVAILABLE, cls="SL", pct=100, fare="180"),
        cls="SL",
    )
    assert found == [("NZM", "BTE", "SRR")]  # Option 1 stays; Option 4 is gone


def test_6_screenshot_split_segment_is_never_even_requested() -> None:
    """VIVEK EXPRESS as planner positions DBRG=0, MXN=1, NCB=2, CAPE=3."""
    statuses = {
        (0, 3): S.WAITLIST,
        (0, 1): S.AVAILABLE,
        (0, 2): S.AVAILABLE,
        (1, 3): S.WAITLIST,
        (2, 3): S.WAITLIST,
        (1, 2): S.AVAILABLE,
    }
    _, executed = drive([ComboSpec(0, 0, 3, (1, 2))], table(statuses))
    assert (1, 2) not in [q.edge for q in executed]  # MXN→NCB: DBRG→NCB already AVAILABLE


# --- Test 7: provider requests ------------------------------------------------------------------
def test_7_available_short_legs_need_only_direct_first_and_last_legs() -> None:
    """15 stops; every leg short of the destination available, every leg into it waitlisted
    (the screenshots' pattern). Before: all 136 forward pairs. Now: 1 + 15 + 15."""
    destination = 16

    def oracle(query: PlannedQuery) -> Status:
        return S.WAITLIST if query.to_index == destination else S.AVAILABLE

    spec = ComboSpec(0, 0, destination, tuple(range(1, destination)))
    planner, executed = drive([spec], oracle)
    assert len(executed) == 1 + 15 + 15
    assert all(q.from_index == 0 or q.to_index == destination for q in executed)
    assert len({q.edge for q in executed}) == len(executed)  # no duplicates
    assert planner.progress()[0].state is ComboState.EXHAUSTED


def test_7_unavailable_ranges_are_still_subdivided() -> None:
    """A→D waitlisted: the planner must still ask A→B, B→D (up to four tickets)."""
    statuses = {
        (0, 4): S.WAITLIST,
        (0, 3): S.WAITLIST,
        (0, 1): S.AVAILABLE,
        (1, 3): S.AVAILABLE,
        (3, 4): S.WAITLIST,
    }
    _, executed = drive([ComboSpec(0, 0, 4, (1, 2, 3))], table(statuses))
    assert (1, 3) in [q.edge for q in executed]


# --- Test 8: a prediction is not availability --------------------------------------------------
def test_8_a_100_percent_prediction_on_a_waitlist_does_not_dominate() -> None:
    found = paths_of(
        ROUTE,
        obs("A", "D", S.WAITLIST, pct=100),
        obs("A", "B", S.AVAILABLE),
        obs("B", "D", S.AVAILABLE),
        obs("D", "Z", S.WAITLIST, pct=40),
    )
    assert ("A", "B", "D", "Z") in found

    # The planner only ever sees statuses: A→D is waitlisted (whatever its prediction), so
    # A→B→D→Z is still explored.
    statuses = {
        (0, 4): S.WAITLIST,
        (0, 3): S.WAITLIST,
        (0, 1): S.AVAILABLE,
        (1, 3): S.AVAILABLE,
        (3, 4): S.WAITLIST,
    }
    _, executed = drive([ComboSpec(0, 0, 4, (1, 2, 3))], table(statuses))
    assert (1, 3) in [q.edge for q in executed]


def test_merged_path_always_outranks_the_dominated_one() -> None:
    """Why pruning is safe: the merged path is never worse on tier, prediction or tickets."""
    observations = [
        obs("A", "D", S.AVAILABLE, fare="900"),
        obs("A", "B", S.AVAILABLE, fare="100"),  # the split is even cheaper …
        obs("B", "D", S.AVAILABLE, fare="100"),
        obs("D", "Z", S.WAITLIST, pct=59, fare="500"),
    ]
    graph = build_graph(key(), observations, {c: i for i, c in enumerate(ROUTE)}, WL_OK)
    every = find_paths(graph, 0, 4, prune_dominated=False)
    ranked = rank_paths([(key(), p) for p in every])
    order = [r.path.stations for r in ranked]
    # … but fewer tickets outrank fare (binding rule), so the split was never above the merge.
    assert order.index(("A", "D", "Z")) < order.index(("A", "B", "D", "Z"))
