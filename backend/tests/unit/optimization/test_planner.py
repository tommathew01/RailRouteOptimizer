from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.domain.enums import AvailabilityStatus as S
from app.optimization.planner import ComboSpec, ComboState, PlannedQuery, QueryPlanner
from app.optimization.policy import SearchFilters

Edge = tuple[int, int]


def spec(
    cid: int = 0, src: int = 0, dst: int = 5, weights: Mapping[int, float] | None = None
) -> ComboSpec:
    return ComboSpec(cid, src, dst, tuple(range(src + 1, dst)), weights or {})


def run(
    planner: QueryPlanner,
    oracle: Mapping[tuple[int, Edge], S | None],
    *,
    budget: int = 1_000,
    wave: int = 4,
    default: S | None = S.NOT_AVAILABLE,
) -> list[PlannedQuery]:
    """Execute waves against a status oracle; returns queries in execution order."""
    executed: list[PlannedQuery] = []
    while not planner.finished:
        queries = planner.next_wave(min(wave, budget - len(executed)))
        if not queries:
            planner.stop()
            break
        for query in queries:
            executed.append(query)
            planner.record(query, oracle.get((query.combo_id, query.edge), default))
    return executed


def edges(queries: list[PlannedQuery]) -> list[Edge]:
    return [q.edge for q in queries]


def test_direct_available_solves_with_one_query() -> None:
    planner = QueryPlanner([spec()], filters=SearchFilters())
    executed = run(planner, {(0, (0, 5)): S.AVAILABLE})
    assert edges(executed) == [(0, 5)]
    assert planner.progress()[0].state is ComboState.SOLVED


def test_direct_first_then_two_segment_candidates_by_weight() -> None:
    planner = QueryPlanner([spec(weights={3: 10, 1: 5})], filters=SearchFilters())
    executed = run(planner, {(0, (0, 5)): S.WAITLIST}, wave=1, budget=4)
    # direct, then first edges of the heaviest intermediates (3, then 1, then 2 by route order)
    assert edges(executed) == [(0, 5), (0, 3), (0, 1), (0, 2)]


def test_second_edge_is_only_queried_after_first_is_usable() -> None:
    oracle = {(0, (0, 5)): S.WAITLIST, (0, (0, 2)): S.AVAILABLE, (0, (2, 5)): S.AVAILABLE}
    executed = run(QueryPlanner([spec()], filters=SearchFilters()), oracle, wave=1)
    queried = edges(executed)
    assert (2, 5) in queried
    for m in (1, 3, 4):  # first edge (0, m) not available -> (m, 5) never requested at depth 2
        assert (m, 5) not in queried
    assert queried.index((0, 2)) < queried.index((2, 5))


def test_each_edge_is_requested_at_most_once() -> None:
    oracle = {(0, e): S.WAITLIST for e in [(0, 5)]} | {
        (0, (0, m)): S.AVAILABLE for m in range(1, 5)
    }
    executed = run(QueryPlanner([spec()], filters=SearchFilters()), oracle)
    assert len(edges(executed)) == len(set(edges(executed)))


def test_known_ineligible_edges_prune_deeper_candidates_without_spending_budget() -> None:
    oracle = {(0, (0, 1)): S.AVAILABLE, (0, (1, 2)): S.AVAILABLE, (0, (2, 3)): S.AVAILABLE}
    executed = run(QueryPlanner([spec(dst=3)], filters=SearchFilters()), oracle)
    queried = edges(executed)
    # (0,3) N/A; depth 2: (0,1) ok -> (1,3) N/A; (0,2) N/A. depth 3: only (0,1,2,3) remains.
    assert queried == [(0, 3), (0, 1), (0, 2), (1, 3), (1, 2), (2, 3)]


def test_solved_combination_stops_and_never_explores_deeper() -> None:
    oracle = {(0, (0, 5)): S.WAITLIST, (0, (0, 2)): S.AVAILABLE, (0, (2, 5)): S.CONFIRMED}
    planner = QueryPlanner([spec()], filters=SearchFilters())
    executed = run(planner, oracle, wave=1)
    assert planner.progress()[0].state is ComboState.SOLVED
    assert all(q.from_index == 0 or q.to_index == 5 for q in executed)  # no middle edges


def test_rac_path_does_not_stop_search_for_all_confirmed_path() -> None:
    oracle = {
        (0, (0, 5)): S.RAC,
        (0, (0, 1)): S.AVAILABLE,
        (0, (1, 3)): S.AVAILABLE,
        (0, (3, 5)): S.AVAILABLE,
    }
    planner = QueryPlanner([spec()], filters=SearchFilters(allow_rac=True))
    executed = run(planner, oracle)
    assert {(1, 3), (3, 5)} <= set(edges(executed))
    assert planner.progress()[0].state is ComboState.SOLVED


def test_max_segments_bounds_exploration() -> None:
    planner = QueryPlanner([spec()], filters=SearchFilters(), max_segments=2)
    executed = run(planner, {(0, (0, m)): S.AVAILABLE for m in range(1, 5)})
    assert all(q.from_index == 0 or q.to_index == 5 for q in executed)
    assert planner.progress()[0].state is ComboState.EXHAUSTED


def test_failed_edges_are_not_retried_and_not_counted_as_unavailable() -> None:
    oracle: dict[tuple[int, Edge], S | None] = {
        (0, (0, 5)): None,
        (0, (0, 2)): S.AVAILABLE,
        (0, (2, 5)): None,
    }
    planner = QueryPlanner([spec()], filters=SearchFilters())
    executed = run(planner, oracle)
    assert edges(executed).count((0, 5)) == 1
    assert edges(executed).count((2, 5)) == 1


def test_budget_exhaustion_leaves_outstanding_work() -> None:
    planner = QueryPlanner([spec(dst=9)], filters=SearchFilters())
    executed = run(planner, {(0, (0, 9)): S.WAITLIST}, budget=3)
    assert len(executed) == 3
    assert planner.progress()[0].state is ComboState.STOPPED
    assert planner.outstanding_edges() > 0


def test_combinations_share_budget_round_robin() -> None:
    specs = [spec(cid) for cid in range(3)]
    planner = QueryPlanner(specs, filters=SearchFilters())
    first = planner.next_wave(3)
    assert sorted(q.combo_id for q in first) == [0, 1, 2]  # every combination's direct first
    for q in first:
        planner.record(q, S.WAITLIST)
    second = planner.next_wave(6)
    counts = {cid: sum(q.combo_id == cid for q in second) for cid in range(3)}
    assert counts == {0: 2, 1: 2, 2: 2}


def test_wave_never_exceeds_requested_size() -> None:
    planner = QueryPlanner([spec(cid) for cid in range(5)], filters=SearchFilters())
    assert len(planner.next_wave(2)) == 2
    assert planner.next_wave(0) == []


def test_planner_is_deterministic() -> None:
    oracle = {(c, (0, 5)): S.WAITLIST for c in range(2)} | {(1, (0, 3)): S.AVAILABLE}
    a = run(QueryPlanner([spec(0), spec(1)], filters=SearchFilters()), oracle)
    b = run(QueryPlanner([spec(0), spec(1)], filters=SearchFilters()), oracle)
    assert a == b


def test_release_returns_query_to_pool() -> None:
    planner = QueryPlanner([spec()], filters=SearchFilters())
    [query] = planner.next_wave(1)
    planner.release(query)
    assert planner.next_wave(1) == [query]


def test_adjacent_source_and_destination_only_query_direct() -> None:
    planner = QueryPlanner([ComboSpec(0, 3, 4, ())], filters=SearchFilters())
    executed = run(planner, {})
    assert edges(executed) == [(3, 4)]
    assert planner.progress()[0].state is ComboState.EXHAUSTED


def test_combinatorial_growth_is_bounded() -> None:
    """60 intermediates: depth-3 candidates are capped instead of exploding (C(60,2)=1770).

    First legs are RAC, not AVAILABLE: an AVAILABLE A→b would (correctly) dominate every
    3-ticket candidate A→a→b→Z and depth 3 would never be explored (D-34).
    """
    wide = ComboSpec(0, 0, 61, tuple(range(1, 61)), {})
    oracle: dict[tuple[int, Edge], S | None] = {(0, (0, 61)): S.WAITLIST}
    oracle |= {(0, (0, m)): S.RAC for m in range(1, 61)}
    oracle |= {(0, (m, 61)): S.RAC for m in range(1, 61)}
    planner = QueryPlanner(
        [wide], filters=SearchFilters(allow_rac=True), max_combinations_per_depth=500
    )
    executed = run(planner, oracle, budget=400, wave=50)
    middle = [q for q in executed if q.from_index != 0 and q.to_index != 61]
    assert len(executed) == 400
    assert middle  # depth 3 reached
    assert len({q.from_index for q in middle} | {q.to_index for q in middle}) <= 32


@pytest.mark.parametrize(
    "bad",
    [ComboSpec(0, 5, 2, ()), ComboSpec(0, 0, 5, (7,))],
)
def test_invalid_specs_rejected(bad: ComboSpec) -> None:
    with pytest.raises(ValueError, match=r"source must precede|strictly between"):
        QueryPlanner([bad], filters=SearchFilters())


def test_duplicate_combo_ids_and_bad_depth_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        QueryPlanner([spec(0), spec(0)], filters=SearchFilters())
    with pytest.raises(ValueError, match="between 1 and 4"):
        QueryPlanner([spec()], filters=SearchFilters(), max_segments=5)
