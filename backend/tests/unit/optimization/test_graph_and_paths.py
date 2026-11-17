from __future__ import annotations

import itertools
from datetime import date

import pytest

from app.domain.enums import Quota
from app.optimization.graph import GraphConsistencyError, SegmentEdge, SegmentGraph, build_graph
from app.optimization.paths import find_paths
from app.optimization.policy import SearchFilters
from tests.unit.optimization.builders import INDEX, START, S, key, obs

ALL = SearchFilters(allow_rac=True, allow_waitlist=True)


def graph(*observations, filters: SearchFilters = ALL) -> SegmentGraph:
    return build_graph(key(), observations, INDEX, filters)


def stations(paths) -> list[tuple[str, ...]]:
    return [p.stations for p in paths]


def test_direct_path() -> None:
    g = graph(obs("TIR", "TVC", S.AVAILABLE))
    assert stations(find_paths(g, 0, 7)) == [("TIR", "TVC")]


def test_two_edge_path() -> None:
    g = graph(obs("TIR", "ERS", S.CONFIRMED), obs("ERS", "TVC", S.AVAILABLE))
    assert stations(find_paths(g, 0, 7)) == [("TIR", "ERS", "TVC")]


def test_four_edge_path_and_five_edge_connection_rejected() -> None:
    hops = ["TIR", "SRR", "TCR", "AWY", "ERS", "TVC"]
    g = graph(*(obs(a, b, S.AVAILABLE) for a, b in itertools.pairwise(hops)))
    assert find_paths(g, 0, 7) == []  # only a 5-ticket chain exists: not allowed
    assert stations(find_paths(g, 0, INDEX["ERS"])) == [("TIR", "SRR", "TCR", "AWY", "ERS")]


@pytest.mark.parametrize("bad", [0, 5, 10])
def test_max_segments_outside_one_to_four_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 4"):
        find_paths(SegmentGraph(key()), 0, 7, max_segments=bad)


def test_max_segments_lower_than_four_is_respected() -> None:
    g = graph(
        obs("TIR", "SRR", S.AVAILABLE),
        obs("SRR", "ERS", S.AVAILABLE),
        obs("ERS", "TVC", S.AVAILABLE),
    )
    assert find_paths(g, 0, 7, max_segments=2) == []
    assert len(find_paths(g, 0, 7, max_segments=3)) == 1


def test_disconnected_edges_produce_no_path() -> None:
    g = graph(obs("TIR", "SRR", S.AVAILABLE), obs("TCR", "TVC", S.AVAILABLE))
    assert find_paths(g, 0, 7) == []


def test_backward_edge_is_rejected() -> None:
    g = SegmentGraph(key())
    with pytest.raises(GraphConsistencyError, match="forward"):
        g.add(SegmentEdge(5, 2, obs("ERS", "TCR", S.AVAILABLE), tier=0))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "foreign",
    [
        obs("TIR", "ERS", S.AVAILABLE, train="99999"),
        obs("TIR", "ERS", S.AVAILABLE, cls="SL"),
        obs("TIR", "ERS", S.AVAILABLE, start=date(2026, 11, 21)),
        obs("TIR", "ERS", S.AVAILABLE, quota=Quota.TATKAL),
    ],
    ids=["other-train", "other-class", "other-date", "other-quota"],
)
def test_cross_train_class_date_quota_edges_are_rejected(foreign) -> None:
    with pytest.raises(GraphConsistencyError):
        build_graph(key(), [obs("ERS", "TVC", S.AVAILABLE), foreign], INDEX, ALL)


def test_gn_quota_is_the_default_graph_quota() -> None:
    assert key().quota is Quota.GENERAL


def test_tatkal_graph_accepts_only_tatkal_edges() -> None:
    tatkal = key(quota=Quota.TATKAL)
    graph = build_graph(
        tatkal,
        [
            obs("TIR", "ERS", S.AVAILABLE, quota=Quota.TATKAL),
            obs("ERS", "TVC", S.AVAILABLE, quota=Quota.TATKAL),
        ],
        INDEX,
        ALL,
    )
    [path] = find_paths(graph, INDEX["TIR"], INDEX["TVC"])
    assert {edge.observation.key.quota for edge in path.edges} == {Quota.TATKAL}
    with pytest.raises(GraphConsistencyError):
        build_graph(
            tatkal,
            [obs("TIR", "ERS", S.AVAILABLE, quota=Quota.TATKAL), obs("ERS", "TVC", S.AVAILABLE)],
            INDEX,
            ALL,
        )


def test_waitlist_excluded_when_filter_false() -> None:
    observations = (obs("TIR", "TCR", S.WAITLIST, pct=80), obs("TCR", "TVC", S.AVAILABLE))
    assert find_paths(graph(*observations, filters=SearchFilters(allow_rac=True)), 0, 7) == []
    assert len(find_paths(graph(*observations), 0, 7)) == 1


def test_rac_excluded_when_filter_false() -> None:
    observations = (obs("TIR", "TCR", S.RAC), obs("TCR", "TVC", S.AVAILABLE))
    assert find_paths(graph(*observations, filters=SearchFilters(allow_waitlist=True)), 0, 7) == []
    assert len(find_paths(graph(*observations, filters=SearchFilters(allow_rac=True)), 0, 7)) == 1


@pytest.mark.parametrize("status", [S.UNKNOWN, S.NOT_AVAILABLE])
def test_unknown_and_not_available_are_never_usable(status: S) -> None:
    g = graph(obs("TIR", "ERS", status), obs("ERS", "TVC", S.AVAILABLE))
    assert g.edge_count == 1
    assert find_paths(g, 0, 7) == []


def test_docs_worked_example() -> None:
    """docs/04 §9: two 3-segment paths; ERS→TVC is shared; KTYM→TVC is unknown."""
    observations = (
        obs("TIR", "SRR", S.CONFIRMED),
        obs("SRR", "ERS", S.AVAILABLE),
        obs("ERS", "TVC", S.RAC),
        obs("TIR", "TCR", S.WAITLIST),
        obs("TCR", "ERS", S.CONFIRMED),
        obs("KTYM", "TVC", S.UNKNOWN),
    )
    rac_and_wl = find_paths(graph(*observations), 0, 7)
    assert stations(rac_and_wl) == [("TIR", "SRR", "ERS", "TVC"), ("TIR", "TCR", "ERS", "TVC")]
    rac_only = find_paths(graph(*observations, filters=SearchFilters(allow_rac=True)), 0, 7)
    assert stations(rac_only) == [("TIR", "SRR", "ERS", "TVC")]
    shared = {id(p.edges[-1].observation) for p in rac_and_wl}
    assert len(shared) == 1  # the same ERS→TVC observation serves both paths


def test_fewer_segments_kept_first_when_truncated_and_order_is_deterministic() -> None:
    codes = ["TIR", "SRR", "TCR", "AWY", "ERS", "TVC"]
    every_pair = [obs(a, b, S.AVAILABLE) for i, a in enumerate(codes) for b in codes[i + 1 :]]
    # Enumeration mechanics only: with dominance pruning (the default) the available direct
    # ticket would dominate every split, leaving just one path.
    first = find_paths(graph(*every_pair), 0, 7, max_paths=3, prune_dominated=False)
    second = find_paths(graph(*reversed(every_pair)), 0, 7, max_paths=3, prune_dominated=False)
    assert stations(first) == stations(second)
    assert [p.segment_count for p in first] == [1, 2, 2]
    assert stations(find_paths(graph(*every_pair), 0, 7)) == [("TIR", "TVC")]


def test_paths_only_use_route_positions_forward() -> None:
    codes = ["TIR", "SRR", "TCR", "TVC"]
    every_pair = [obs(a, b, S.AVAILABLE) for i, a in enumerate(codes) for b in codes[i + 1 :]]
    for path in find_paths(graph(*every_pair), 0, 7):
        assert list(path.indices) == sorted(set(path.indices))
        assert path.stations[0] == "TIR"
        assert path.stations[-1] == "TVC"


def test_start_date_is_part_of_identity() -> None:
    assert key(start=START) != key(start=date(2026, 11, 21))
