"""Adaptive, budget-aware availability query planner (doc 04 §6; decision D-04). Pure: no I/O.

For every (train, class) *combination* the planner explores candidate paths by increasing number
of segments: the direct segment first, then 2-, 3- and 4-segment paths. Within a depth, candidates
are ordered by (unknown edges needed, heuristic weight of their intermediate stops, route order).

Query order rules (documented and tested):

* A candidate's next edge is requested only after all its earlier edges are known usable.
* A candidate containing any edge already known ineligible (not available, filtered out,
  unknown status) or failed is pruned without spending a request. Failed or unqueried edges are
  never treated as *unavailable*; they are simply not usable in this search.
* Each distinct edge is requested at most once per search.
* Combinations share the request budget round-robin, one request per combination per round.
* A combination stops as soon as it has a complete all-confirmed/available path: deeper paths
  can never outrank it.

The caller executes each wave, reports every result with :meth:`QueryPlanner.record`, and calls
:meth:`QueryPlanner.stop` when the budget or deadline is reached.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.enums import AvailabilityStatus, StatusTier
from app.optimization.policy import (
    MAX_SEGMENTS,
    EdgeEligibility,
    SearchFilters,
    classify,
    status_tier,
)

Edge = tuple[int, int]
Path = tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ComboSpec:
    combo_id: int
    source_index: int
    destination_index: int
    #: Eligible intermediate boundaries in route order (already capped by the caller).
    intermediates: tuple[int, ...]
    #: Heuristic weight per intermediate; higher is explored earlier (e.g. halt minutes).
    node_weight: Mapping[int, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlannedQuery:
    combo_id: int
    from_index: int
    to_index: int

    @property
    def edge(self) -> Edge:
        return (self.from_index, self.to_index)


class EdgeState(StrEnum):
    UNQUERIED = "UNQUERIED"
    SELECTED = "SELECTED"
    USABLE = "USABLE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ComboState(StrEnum):
    ACTIVE = "ACTIVE"
    SOLVED = "SOLVED"
    EXHAUSTED = "EXHAUSTED"
    STOPPED = "STOPPED"


class _Eval(StrEnum):
    PRUNED = "PRUNED"
    COMPLETE = "COMPLETE"
    WAITING = "WAITING"
    NEEDS = "NEEDS"


@dataclass
class _Combo:
    spec: ComboSpec
    depth: int = 0
    candidates: list[Path] = field(default_factory=list)
    cursor: int = 0
    edges: dict[Edge, EdgeState] = field(default_factory=dict)
    tiers: dict[Edge, StatusTier] = field(default_factory=dict)
    state: ComboState = ComboState.ACTIVE
    best_tier: StatusTier | None = None

    def edge_state(self, edge: Edge) -> EdgeState:
        return self.edges.get(edge, EdgeState.UNQUERIED)


@dataclass(frozen=True, slots=True)
class ComboProgress:
    combo_id: int
    state: ComboState
    depth_reached: int
    edges_known: int
    best_complete_tier: StatusTier | None


def _edges(path: Path) -> list[Edge]:
    return list(itertools.pairwise(path))


class QueryPlanner:
    def __init__(
        self,
        specs: Sequence[ComboSpec],
        *,
        filters: SearchFilters,
        max_segments: int = MAX_SEGMENTS,
        max_candidates_per_depth: int = 5_000,
        max_combinations_per_depth: int = 20_000,
    ) -> None:
        if not 1 <= max_segments <= MAX_SEGMENTS:
            raise ValueError(f"max_segments must be between 1 and {MAX_SEGMENTS}")
        ids = [spec.combo_id for spec in specs]
        if len(ids) != len(set(ids)):
            raise ValueError("combo ids must be unique")
        for spec in specs:
            if spec.source_index >= spec.destination_index:
                raise ValueError("source must precede destination")
            if any(not spec.source_index < m < spec.destination_index for m in spec.intermediates):
                raise ValueError("intermediates must lie strictly between source and destination")
        self._filters = filters
        self._max_segments = max_segments
        self._max_candidates = max_candidates_per_depth
        self._max_combinations = max_combinations_per_depth
        self._combos: dict[int, _Combo] = {spec.combo_id: _Combo(spec) for spec in specs}
        self._order = ids
        self._rotation = 0

    # --- Public API -----------------------------------------------------------------------------
    def next_wave(self, max_queries: int) -> list[PlannedQuery]:
        if max_queries <= 0:
            return []
        for combo in self._combos.values():
            self._advance(combo)
        active = [cid for cid in self._order if self._combos[cid].state is ComboState.ACTIVE]
        if not active:
            return []
        start = self._rotation % len(active)
        self._rotation += 1
        order = active[start:] + active[:start]
        pointers = {cid: self._combos[cid].cursor for cid in order}
        wave: list[PlannedQuery] = []
        progressed = True
        while len(wave) < max_queries and progressed:
            progressed = False
            for cid in order:
                if len(wave) >= max_queries:
                    break
                query = self._pick(self._combos[cid], pointers)
                if query is not None:
                    wave.append(query)
                    progressed = True
        return wave

    def record(self, query: PlannedQuery, status: AvailabilityStatus | None) -> None:
        """Report an executed query. ``status=None`` means the provider call failed."""
        combo = self._combos[query.combo_id]
        if status is None:
            combo.edges[query.edge] = EdgeState.FAILED
            return
        if classify(status, self._filters) is EdgeEligibility.USABLE:
            tier = status_tier(status)
            if tier is None:  # pragma: no cover - classify() and status_tier() agree
                combo.edges[query.edge] = EdgeState.BLOCKED
                return
            combo.edges[query.edge] = EdgeState.USABLE
            combo.tiers[query.edge] = tier
        else:
            combo.edges[query.edge] = EdgeState.BLOCKED

    def release(self, query: PlannedQuery) -> None:
        """Return a selected-but-not-executed query to the pool (e.g. budget refused it)."""
        combo = self._combos[query.combo_id]
        if combo.edge_state(query.edge) is EdgeState.SELECTED:
            combo.edges.pop(query.edge, None)

    def stop(self) -> None:
        for combo in self._combos.values():
            if combo.state is ComboState.ACTIVE:
                combo.state = ComboState.STOPPED

    @property
    def finished(self) -> bool:
        for combo in self._combos.values():
            self._advance(combo)
        return all(combo.state is not ComboState.ACTIVE for combo in self._combos.values())

    def outstanding_edges(self) -> int:
        """Distinct edges still needed at the current depth of unfinished combinations."""
        total = 0
        for combo in self._combos.values():
            if combo.state not in (ComboState.ACTIVE, ComboState.STOPPED):
                continue
            needed: set[Edge] = set()
            for path in combo.candidates[combo.cursor :]:
                if self._evaluate(combo, path)[0] is _Eval.PRUNED:
                    continue
                needed.update(
                    e
                    for e in _edges(path)
                    if combo.edge_state(e) in (EdgeState.UNQUERIED, EdgeState.SELECTED)
                )
            total += len(needed)
        return total

    def progress(self) -> list[ComboProgress]:
        report = []
        for cid in self._order:
            combo = self._combos[cid]
            self._best_complete_tier(combo)
            known = sum(1 for state in combo.edges.values() if state is not EdgeState.SELECTED)
            report.append(ComboProgress(cid, combo.state, combo.depth, known, combo.best_tier))
        return report

    # --- Internals ------------------------------------------------------------------------------
    def _evaluate(self, combo: _Combo, path: Path) -> tuple[_Eval, Edge | None]:
        edges = _edges(path)
        states = [combo.edge_state(e) for e in edges]
        if any(s in (EdgeState.BLOCKED, EdgeState.FAILED) for s in states):
            return _Eval.PRUNED, None
        for edge, state in zip(edges, states, strict=True):
            if state is EdgeState.USABLE:
                continue
            if state is EdgeState.UNQUERIED:
                return _Eval.NEEDS, edge
            return _Eval.WAITING, edge
        return _Eval.COMPLETE, None

    def _path_tier(self, combo: _Combo, path: Path) -> StatusTier:
        return max(combo.tiers[e] for e in _edges(path))

    def _best_complete_tier(self, combo: _Combo) -> StatusTier | None:
        """Best tier among complete candidates so far (all depths explored)."""
        for path in combo.candidates:
            if self._evaluate(combo, path)[0] is _Eval.COMPLETE:
                tier = self._path_tier(combo, path)
                if combo.best_tier is None or tier < combo.best_tier:
                    combo.best_tier = tier
        return combo.best_tier

    def _limited_nodes(
        self, nodes: tuple[int, ...], choose: int, weight: Mapping[int, float]
    ) -> tuple[int, ...]:
        """Bound combinatorial growth: keep the highest-weight stops for deep searches."""
        if choose <= 0 or math.comb(len(nodes), choose) <= self._max_combinations:
            return nodes
        keep = len(nodes)
        while keep > choose and math.comb(keep, choose) > self._max_combinations:
            keep -= 1
        best = sorted(nodes, key=lambda n: (-weight.get(n, 0.0), n))[:keep]
        return tuple(sorted(best))

    def _generate(self, combo: _Combo, depth: int) -> list[Path]:
        spec = combo.spec
        choose = depth - 1
        nodes = self._limited_nodes(spec.intermediates, choose, spec.node_weight)
        if choose > len(nodes):
            return []
        scored: list[tuple[tuple[int, float, Path], Path]] = []
        for middle in itertools.combinations(nodes, choose):
            path: Path = (spec.source_index, *middle, spec.destination_index)
            states = [combo.edge_state(e) for e in _edges(path)]
            if any(s in (EdgeState.BLOCKED, EdgeState.FAILED) for s in states):
                continue
            unknown = sum(1 for s in states if s is not EdgeState.USABLE)
            weight = sum(spec.node_weight.get(m, 0.0) for m in middle)
            scored.append(((unknown, -weight, path), path))
        scored.sort(key=lambda item: item[0])
        return [path for _, path in scored[: self._max_candidates]]

    def _advance(self, combo: _Combo) -> None:
        while combo.state is ComboState.ACTIVE:
            if combo.depth == 0:
                combo.depth = 1
                combo.candidates = self._generate(combo, 1)
                combo.cursor = 0
            while combo.cursor < len(combo.candidates):
                verdict, _ = self._evaluate(combo, combo.candidates[combo.cursor])
                if verdict in (_Eval.PRUNED, _Eval.COMPLETE):
                    combo.cursor += 1
                else:
                    break
            if self._best_complete_tier(combo) is StatusTier.ALL_CONFIRMED_OR_AVAILABLE:
                combo.state = ComboState.SOLVED
                return
            if combo.cursor < len(combo.candidates):
                return
            if combo.depth >= self._max_segments:
                combo.state = ComboState.EXHAUSTED
                return
            combo.depth += 1
            combo.candidates = self._generate(combo, combo.depth)
            combo.cursor = 0

    def _pick(self, combo: _Combo, pointers: dict[int, int]) -> PlannedQuery | None:
        if combo.state is not ComboState.ACTIVE:
            return None
        index = pointers[combo.spec.combo_id]
        while index < len(combo.candidates):
            verdict, edge = self._evaluate(combo, combo.candidates[index])
            index += 1
            if verdict is _Eval.NEEDS and edge is not None:
                combo.edges[edge] = EdgeState.SELECTED
                pointers[combo.spec.combo_id] = index
                return PlannedQuery(combo.spec.combo_id, edge[0], edge[1])
        pointers[combo.spec.combo_id] = index
        return None
