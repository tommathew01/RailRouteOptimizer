"""Bounded path enumeration over the segment DAG (doc 04 §4).

Iterative deepening (1, 2, … ``max_segments`` edges) so that, when ``max_paths`` truncates the
output, paths with fewer tickets are always kept first. Order within a depth is lexicographic in
route positions, so results are deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.optimization.graph import SegmentEdge, SegmentGraph
from app.optimization.policy import MAX_SEGMENTS


@dataclass(frozen=True, slots=True)
class CandidatePath:
    edges: tuple[SegmentEdge, ...]

    @property
    def segment_count(self) -> int:
        return len(self.edges)

    @property
    def stations(self) -> tuple[str, ...]:
        return (self.edges[0].from_station, *(edge.to_station for edge in self.edges))

    @property
    def indices(self) -> tuple[int, ...]:
        return (self.edges[0].from_index, *(edge.to_index for edge in self.edges))


def find_paths(
    graph: SegmentGraph,
    source_index: int,
    destination_index: int,
    *,
    max_segments: int = MAX_SEGMENTS,
    max_paths: int = 50,
) -> list[CandidatePath]:
    if not 1 <= max_segments <= MAX_SEGMENTS:
        raise ValueError(f"max_segments must be between 1 and {MAX_SEGMENTS}")
    if source_index >= destination_index:
        return []

    results: list[CandidatePath] = []

    def walk(node: int, path: list[SegmentEdge], depth: int) -> None:
        if len(results) >= max_paths:
            return
        if len(path) == depth:
            if node == destination_index:
                results.append(CandidatePath(tuple(path)))
            return
        for edge in graph.outgoing(node):
            if edge.to_index > destination_index:
                break  # sorted ascending: nothing further can reach the destination
            if path and path[-1].to_index != edge.from_index:
                continue  # contiguity (guaranteed by construction; kept as an explicit guard)
            path.append(edge)
            walk(edge.to_index, path, depth)
            path.pop()

    for depth in range(1, max_segments + 1):
        walk(source_index, [], depth)
        if len(results) >= max_paths:
            break
    return results
