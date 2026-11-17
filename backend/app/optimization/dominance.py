"""Dominated split-ticket paths (docs/08 D-34). Pure: no I/O.

A path is **dominated** when two or more of its consecutive segments, from stop ``a`` to stop ``b``,
could be replaced by the single segment ``a → b`` and that segment is known to be
CONFIRMED/AVAILABLE — on the same train run, class and quota. (Callers only ever look up segments
of one graph or planner combination, which fixes train, origin date, class and quota.)

Why removing such a path never loses a better option. Merging the run gives a path that:

* uses only segments the dominated path needs, plus the AVAILABLE one — so it is bookable
  whenever the dominated path is, with the same boarding and destination stations;
* has a status tier no worse (the merged segment is tier 0) and a subset of its RAC/waitlist
  segments, so its prediction floor is no lower (ranking keys 1 and 2);
* has strictly fewer tickets (ranking key 3).

So the merged path always ranks strictly higher. The only thing a split can win on is total fare
(ranking key 4), which the binding product rules already place below the number of tickets.

Only CONFIRMED/AVAILABLE dominates. A RAC or waitlisted segment never suppresses alternatives,
and a provider prediction (even 100 %) never counts as availability.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

#: ``is_available(a, b)``: is the direct segment from route position ``a`` to ``b`` known to be
#: CONFIRMED/AVAILABLE?
AvailableLookup = Callable[[int, int], bool]


def dominating_run(indices: Sequence[int], is_available: AvailableLookup) -> tuple[int, int] | None:
    """Positions ``(i, j)`` in ``indices`` (``j >= i + 2``) whose stops are joined by a known
    AVAILABLE segment, preferring the longest run; ``None`` when the path is not dominated."""
    count = len(indices)
    for span in range(count - 1, 1, -1):
        for i in range(count - span):
            if is_available(indices[i], indices[i + span]):
                return i, i + span
    return None


def is_dominated(indices: Sequence[int], is_available: AvailableLookup) -> bool:
    return dominating_run(indices, is_available) is not None


def last_stop_dominated(indices: Sequence[int], is_available: AvailableLookup) -> bool:
    """Incremental check while extending a path: does a run *ending at the last stop* dominate?

    Runs ending earlier were checked when the path was shorter, and domination is inherited by
    every extension, so path searches can stop exploring such a prefix.
    """
    last = indices[-1]
    return any(is_available(indices[i], last) for i in range(len(indices) - 2))
