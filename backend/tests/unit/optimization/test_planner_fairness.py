"""Fair scheduling and progressive deepening across combinations (docs/08 D-27).

Regression tests for the starvation bug: the old planner shifted its starting point by one
combination per wave, so with B budget and W queries per wave only about B/W + W - 1 combinations
were ever queried and later trains / Tatkal combinations never got even their direct check.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from app.domain.enums import AvailabilityStatus as S
from app.optimization.planner import ComboSpec, ComboState, PlannedQuery, QueryPlanner
from app.optimization.policy import SearchFilters

Edge = tuple[int, int]
Oracle = Callable[[PlannedQuery], S | None]

TRAINS, CLASSES, QUOTAS = 5, 4, 2
DESTINATION = 16  # 15 intermediate stops, like a typical long-distance route


def grid_specs(
    n: int = TRAINS * CLASSES * QUOTAS, destination: int = DESTINATION
) -> list[ComboSpec]:
    """``n`` combinations in round-robin order (the search interleaves GN/TQ the same way)."""
    middle = tuple(range(1, destination))
    return [
        ComboSpec(cid, 0, destination, middle, {m: float(m % 5) for m in middle})
        for cid in range(n)
    ]


def is_direct(query: PlannedQuery, destination: int = DESTINATION) -> bool:
    return query.edge == (0, destination)


def waitlisted(_: PlannedQuery) -> S | None:
    return S.WAITLIST


def drive(
    planner: QueryPlanner, oracle: Oracle, *, budget: int, wave: int
) -> list[list[PlannedQuery]]:
    """The JourneySearchService loop: waves of min(wave, remaining) until budget or done."""
    waves: list[list[PlannedQuery]] = []
    used = 0
    while used < budget and not planner.finished:
        queries = planner.next_wave(min(wave, budget - used))
        if not queries:
            break
        waves.append(queries)
        for query in queries:
            used += 1
            planner.record(query, oracle(query))
    planner.stop()
    return waves


def flat(waves: list[list[PlannedQuery]]) -> list[PlannedQuery]:
    return [q for wave in waves for q in wave]


# --- 1-3: every combination's direct check first ---------------------------------------------
def test_five_trains_four_classes_two_quotas_all_get_their_direct_check() -> None:
    specs = grid_specs()
    assert len(specs) == 40
    for budget, wave in ((40, 4), (100, 8), (300, 8)):
        executed = flat(
            drive(
                QueryPlanner(specs, filters=SearchFilters()), waitlisted, budget=budget, wave=wave
            )
        )
        first = executed[: len(specs)]
        assert all(is_direct(q) for q in first), (budget, wave)
        assert sorted(q.combo_id for q in first) == list(range(40))
        assert not any(is_direct(q) for q in executed[len(specs) :])


def test_budget_of_exactly_the_combinations_buys_one_direct_each() -> None:
    executed = flat(
        drive(QueryPlanner(grid_specs(), filters=SearchFilters()), waitlisted, budget=40, wave=8)
    )
    assert Counter(q.combo_id for q in executed) == Counter(range(40))
    assert all(is_direct(q) for q in executed)


def test_budget_smaller_than_the_combinations_spends_everything_on_distinct_directs() -> None:
    planner = QueryPlanner(grid_specs(), filters=SearchFilters())
    executed = flat(drive(planner, waitlisted, budget=30, wave=4))
    assert len(executed) == 30
    assert all(is_direct(q) for q in executed)  # no deeper query while a direct is pending
    assert len({q.combo_id for q in executed}) == 30
    # Round-robin order alternates quotas (even ids GN, odd ids TQ here): both get half.
    assert Counter(q.combo_id % 2 for q in executed) == {0: 15, 1: 15}
    not_reached = [p for p in planner.progress() if p.edges_known == 0]
    assert len(not_reached) == 10
    assert all(p.state is ComboState.STOPPED for p in not_reached)


def test_old_sliding_window_starvation_is_gone() -> None:
    """B=30, W=4 used to reach at most 30/4 + 4 - 1 = 10 combinations; B=100, W=8 at most 19."""
    for budget, wave in ((30, 4), (100, 8)):
        executed = flat(
            drive(
                QueryPlanner(grid_specs(), filters=SearchFilters()),
                waitlisted,
                budget=budget,
                wave=wave,
            )
        )
        assert len({q.combo_id for q in executed}) == min(40, budget)


# --- 4: the round-robin cursor ----------------------------------------------------------------
def test_cursor_moves_past_the_combination_of_every_scheduled_query() -> None:
    planner = QueryPlanner(grid_specs(5), filters=SearchFilters())
    assert planner.cursor == 0
    for _ in range(4):
        wave = planner.next_wave(2)
        assert planner.cursor == (wave[-1].combo_id + 1) % 5
        for query in wave:
            planner.record(query, S.WAITLIST)


def test_ties_rotate_across_waves_instead_of_restarting_at_the_first_combination() -> None:
    planner = QueryPlanner(grid_specs(3), filters=SearchFilters())
    for query in planner.next_wave(3):  # directs of 0, 1, 2
        planner.record(query, S.WAITLIST)
    served: list[list[int]] = []
    for _ in range(3):
        wave = planner.next_wave(2)
        served.append([q.combo_id for q in wave])
        for query in wave:
            planner.record(query, S.NOT_AVAILABLE)
    assert served == [[0, 1], [2, 0], [1, 2]]


def test_a_released_query_does_not_count_as_service() -> None:
    planner = QueryPlanner(grid_specs(3), filters=SearchFilters())
    first = planner.next_wave(1)
    planner.release(first[0])
    again = planner.next_wave(3)
    assert sorted(q.combo_id for q in again) == [0, 1, 2]
    assert all(is_direct(q) for q in again)


# --- 5-7: finished combinations, redistribution, progressive deepening -----------------------
def test_finished_combinations_leave_and_the_rest_keep_being_served() -> None:
    solved = {0, 2}

    def oracle(query: PlannedQuery) -> S | None:
        return S.AVAILABLE if query.combo_id in solved and is_direct(query) else S.WAITLIST

    planner = QueryPlanner(grid_specs(4), filters=SearchFilters())
    executed = flat(drive(planner, oracle, budget=40, wave=4))
    per_combo = Counter(q.combo_id for q in executed)
    assert per_combo[0] == per_combo[2] == 1  # solved by their direct ticket, never again
    assert per_combo[1] > 1
    assert per_combo[3] > 1
    assert abs(per_combo[1] - per_combo[3]) <= 1  # the freed budget is split evenly
    states = {p.combo_id: p.state for p in planner.progress()}
    assert states[0] is states[2] is ComboState.SOLVED


def test_unused_share_of_a_cheap_combination_flows_to_the_others() -> None:
    """Combination 0 has two stops (exhausted after a few queries); 1 and 2 have fifteen."""
    specs = [ComboSpec(0, 0, 3, (1, 2), {}), *grid_specs(3)[1:]]

    def oracle(query: PlannedQuery) -> S | None:
        return S.NOT_AVAILABLE

    planner = QueryPlanner(specs, filters=SearchFilters())
    executed = flat(drive(planner, oracle, budget=30, wave=3))
    per_combo = Counter(q.combo_id for q in executed)
    assert len(executed) == 30
    assert planner.progress()[0].state is ComboState.EXHAUSTED
    assert per_combo[0] == 3  # (0,3), (0,1), (0,2): every path through them is blocked
    assert abs(per_combo[1] - per_combo[2]) <= 1
    assert per_combo[1] + per_combo[2] == 27


def test_no_combination_explores_deeper_while_another_has_shallower_work() -> None:
    """With one query per wave nothing is in flight, so each pick must be at the lowest depth.

    Route 0..8: the only bookable paths need four tickets 0 → {1,2} → {3..6} → 7 → 8, so every
    combination walks through all four levels before it is solved.
    """

    def oracle(query: PlannedQuery) -> S | None:
        a, b = query.edge
        bookable = (
            (a == 0 and b in (1, 2))
            or (a in (1, 2) and 3 <= b <= 6)
            or (3 <= a <= 6 and b == 7)
            or (a, b) == (7, 8)
        )
        return S.AVAILABLE if bookable else S.NOT_AVAILABLE

    planner = QueryPlanner(grid_specs(6, destination=8), filters=SearchFilters())
    picks = 0
    while not planner.finished and picks < 600:
        [query] = planner.next_wave(1)
        progress = planner.progress()  # depths after the advance done by next_wave
        depth = {p.combo_id: p.depth_reached for p in progress}
        active = {p.combo_id for p in progress if p.state is ComboState.ACTIVE}
        assert depth[query.combo_id] == min(depth[c] for c in active)
        planner.record(query, oracle(query))
        picks += 1
    assert planner.finished
    assert all(p.state is ComboState.SOLVED and p.depth_reached == 4 for p in planner.progress())


def test_combinations_without_any_result_go_first_within_a_round() -> None:
    """Waitlist allowed: combination 0 already has a (waitlisted) direct ticket, 1 has nothing."""

    def oracle(query: PlannedQuery) -> S | None:
        if is_direct(query):
            return S.WAITLIST if query.combo_id == 0 else S.NOT_AVAILABLE
        return S.NOT_AVAILABLE

    planner = QueryPlanner(grid_specs(2), filters=SearchFilters(allow_waitlist=True))
    for query in planner.next_wave(2):
        planner.record(query, oracle(query))
    order = []
    for _ in range(6):
        [query] = planner.next_wave(1)
        order.append(query.combo_id)
        planner.record(query, oracle(query))
    assert order == [1, 0, 1, 0, 1, 0]  # equal shares; the one with nothing yet leads each round
    assert planner.progress()[0].best_complete_tier is not None


# --- 8: no duplicates -------------------------------------------------------------------------
def test_no_segment_is_requested_twice_with_forty_combinations() -> None:
    def oracle(query: PlannedQuery) -> S | None:
        # RAC / waitlist only: never "solved", so exploration is exhaustive within the budget.
        return S.RAC if (query.from_index * 7 + query.to_index + query.combo_id) % 4 else S.WAITLIST

    filters = SearchFilters(allow_rac=True, allow_waitlist=True)
    planner = QueryPlanner(grid_specs(), filters=filters)
    executed = flat(drive(planner, oracle, budget=500, wave=8))
    keys = [(q.combo_id, q.edge) for q in executed]
    assert len(keys) == len(set(keys))
    assert len(executed) == 500
