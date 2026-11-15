from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from app.domain.enums import Quota, StatusTier
from app.optimization.graph import GraphKey, build_graph
from app.optimization.paths import CandidatePath, find_paths
from app.optimization.policy import SearchFilters
from app.optimization.ranking import rank_paths, summarize_fare
from tests.unit.optimization.builders import INDEX, OBSERVED, S, key, obs

ALL = SearchFilters(allow_rac=True, allow_waitlist=True)


def path_of(
    *observations, cls: str = "3A", train: str = "12345", quota: Quota = Quota.GENERAL
) -> tuple[GraphKey, CandidatePath]:
    k = key(train=train, cls=cls, quota=quota)
    graph = build_graph(k, observations, INDEX, ALL)
    src, dst = INDEX[observations[0].key.from_station], INDEX[observations[-1].key.to_station]
    [path] = [p for p in find_paths(graph, src, dst) if p.segment_count == len(observations)]
    return k, path


def order(*candidates) -> list[tuple[str, ...]]:
    return [r.path.stations for r in rank_paths(candidates)]


def test_status_tier_outranks_prediction() -> None:
    confirmed = path_of(obs("TIR", "ERS", S.AVAILABLE), obs("ERS", "TVC", S.AVAILABLE))
    waitlisted_high = path_of(obs("TIR", "TVC", S.WAITLIST, pct=99))
    rac = path_of(obs("TIR", "TCR", S.RAC, pct=95), obs("TCR", "TVC", S.AVAILABLE))
    ranked = rank_paths([waitlisted_high, rac, confirmed])
    assert [r.status_tier for r in ranked] == [
        StatusTier.ALL_CONFIRMED_OR_AVAILABLE,
        StatusTier.INCLUDES_RAC,
        StatusTier.INCLUDES_WAITLIST,
    ]


def test_direct_available_beats_split_available_regardless_of_predictions() -> None:
    """D-03: predictions on confirmed/available segments never outweigh fewer tickets."""
    direct = path_of(obs("TIR", "TVC", S.AVAILABLE))
    split = path_of(
        obs("TIR", "ERS", S.AVAILABLE, pct=100), obs("ERS", "TVC", S.AVAILABLE, pct=100)
    )
    assert order(split, direct) == [("TIR", "TVC"), ("TIR", "ERS", "TVC")]


def test_within_tier_higher_prediction_floor_first_and_missing_last() -> None:
    strong = path_of(obs("TIR", "TCR", S.WAITLIST, pct=80), obs("TCR", "TVC", S.WAITLIST, pct=70))
    weak = path_of(obs("TIR", "TVC", S.WAITLIST, pct=60))
    missing = path_of(obs("TIR", "ERS", S.WAITLIST), obs("ERS", "TVC", S.AVAILABLE))
    ranked = rank_paths([missing, weak, strong])
    assert [r.prediction_floor for r in ranked] == [70.0, 60.0, None]
    # prediction outranks segment count within a tier (doc 04 ordering)
    assert ranked[0].path.segment_count == 2


def test_prediction_floor_is_minimum_never_a_product() -> None:
    _, path = path_of(obs("TIR", "TCR", S.RAC, pct=90), obs("TCR", "TVC", S.WAITLIST, pct=50))
    [ranked] = rank_paths([(key(), path)])
    assert ranked.prediction_floor == 50.0  # not 45.0 (0.9 * 0.5)
    assert (ranked.predictions_present, ranked.predictions_needed) == (2, 2)


def test_partial_predictions_count_as_missing() -> None:
    _, path = path_of(obs("TIR", "TCR", S.RAC, pct=90), obs("TCR", "TVC", S.WAITLIST))
    [ranked] = rank_paths([(key(), path)])
    assert ranked.prediction_floor is None
    assert (ranked.predictions_present, ranked.predictions_needed) == (1, 2)
    assert any("1 of 2" in line for line in ranked.explanation)


def test_fewer_segments_then_fare_when_complete() -> None:
    two_cheap = path_of(
        obs("TIR", "ERS", S.AVAILABLE, fare="300"), obs("ERS", "TVC", S.AVAILABLE, fare="200")
    )
    two_dear = path_of(
        obs("TIR", "TCR", S.AVAILABLE, fare="400"), obs("TCR", "TVC", S.AVAILABLE, fare="400")
    )
    two_unpriced = path_of(obs("TIR", "SRR", S.AVAILABLE, fare="1"), obs("SRR", "TVC", S.AVAILABLE))
    three = path_of(
        obs("TIR", "SRR", S.AVAILABLE, fare="1"),
        obs("SRR", "TCR", S.AVAILABLE, fare="1"),
        obs("TCR", "TVC", S.AVAILABLE, fare="1"),
    )
    assert order(three, two_unpriced, two_dear, two_cheap) == [
        ("TIR", "ERS", "TVC"),
        ("TIR", "TCR", "TVC"),
        ("TIR", "SRR", "TVC"),
        ("TIR", "SRR", "TCR", "TVC"),
    ]


def test_incomplete_or_mixed_currency_fares_have_no_total() -> None:
    _, partial = path_of(obs("TIR", "ERS", S.AVAILABLE, fare="300"), obs("ERS", "TVC", S.AVAILABLE))
    _, mixed = path_of(
        obs("TIR", "ERS", S.AVAILABLE, fare="300"),
        obs("ERS", "TVC", S.AVAILABLE, fare="5", currency="USD"),
    )
    _, full = path_of(
        obs("TIR", "ERS", S.AVAILABLE, fare="300.50"), obs("ERS", "TVC", S.AVAILABLE, fare="199.50")
    )
    assert summarize_fare(partial).complete is False
    assert summarize_fare(partial).total is None
    assert summarize_fare(mixed).complete is False
    assert summarize_fare(full).total == Decimal("500.00")


def test_fresher_observations_win_ties() -> None:
    old = path_of(
        obs("TIR", "ERS", S.AVAILABLE, observed_at=OBSERVED - timedelta(minutes=5)),
        obs("ERS", "TVC", S.AVAILABLE),
    )
    new = path_of(obs("TIR", "TCR", S.AVAILABLE), obs("TCR", "TVC", S.AVAILABLE))
    assert order(old, new)[0] == ("TIR", "TCR", "TVC")


def test_ranking_is_deterministic_for_shuffled_input() -> None:
    candidates = [
        path_of(obs("TIR", "TVC", S.WAITLIST, pct=40)),
        path_of(obs("TIR", "ERS", S.AVAILABLE), obs("ERS", "TVC", S.AVAILABLE)),
        path_of(obs("TIR", "TCR", S.AVAILABLE), obs("TCR", "TVC", S.AVAILABLE)),
        path_of(obs("TIR", "TVC", S.AVAILABLE, cls="SL"), cls="SL"),
        path_of(obs("TIR", "TVC", S.AVAILABLE, train="11111"), train="11111"),
    ]
    expected = [(r.key, r.path.stations, r.rank) for r in rank_paths(candidates)]
    for seed in range(5):
        shuffled = candidates[:]
        random.Random(seed).shuffle(shuffled)
        assert [(r.key, r.path.stations, r.rank) for r in rank_paths(shuffled)] == expected
    assert [rank for _, _, rank in expected] == [1, 2, 3, 4, 5]


def test_limit_and_explanations() -> None:
    k, path = path_of(
        obs("TIR", "TCR", S.RAC, pct=88, fare="250"), obs("TCR", "TVC", S.AVAILABLE, fare="250")
    )
    [ranked] = rank_paths([(k, path), path_of(obs("TIR", "TVC", S.WAITLIST))], limit=1)
    assert ranked.rank == 1
    assert ranked.explanation == (
        "Includes RAC on 1 segment(s).",
        "Lowest RailKit estimate on RAC/waitlist segments: 88%.",
        "2 separate tickets.",
        "Total fare INR 500.00 (every segment priced).",
    )


def test_candidate_path_helpers() -> None:
    _, path = path_of(obs("TIR", "ERS", S.AVAILABLE), obs("ERS", "TVC", S.AVAILABLE))
    assert isinstance(path, CandidatePath)
    assert path.indices == (0, 4, 7)


# --- Quotas: separate search spaces, same ranking rules -----------------------------------------
def test_quota_never_outranks_availability() -> None:
    tq = Quota.TATKAL
    general_waitlist = path_of(obs("TIR", "TVC", S.WAITLIST, pct=90))
    tatkal_available = path_of(
        obs("TIR", "ERS", S.AVAILABLE, quota=tq),
        obs("ERS", "TVC", S.AVAILABLE, quota=tq),
        quota=tq,
    )
    ranked = rank_paths([general_waitlist, tatkal_available])
    assert [r.key.quota for r in ranked] == [Quota.TATKAL, Quota.GENERAL]


def test_identical_paths_in_two_quotas_stay_separate_and_order_deterministically() -> None:
    tq = Quota.TATKAL
    general = path_of(obs("TIR", "ERS", S.AVAILABLE), obs("ERS", "TVC", S.AVAILABLE))
    tatkal = path_of(
        obs("TIR", "ERS", S.AVAILABLE, quota=tq),
        obs("ERS", "TVC", S.AVAILABLE, quota=tq),
        quota=tq,
    )
    for candidates in ([general, tatkal], [tatkal, general]):
        ranked = rank_paths(candidates)
        assert [r.key.quota for r in ranked] == [Quota.GENERAL, Quota.TATKAL]
        for item in ranked:  # every edge of a path carries the path's own quota
            assert {e.observation.key.quota for e in item.path.edges} == {item.key.quota}


def test_cheaper_general_fare_wins_over_tatkal_on_equal_status() -> None:
    tq = Quota.TATKAL
    general = path_of(obs("TIR", "TVC", S.AVAILABLE, fare="500"))
    tatkal = path_of(obs("TIR", "TVC", S.AVAILABLE, quota=tq, fare="650"), quota=tq)
    assert [r.key.quota for r in rank_paths([tatkal, general])] == [Quota.GENERAL, Quota.TATKAL]
