# 04 — Availability Discovery and Optimization Engine

## 1. Objective

For one train, journey date, selected class and selected quota (General or Tatkal),
find the best contiguous sequence of between one and four checked segments connecting source to destination.

The optimizer receives normalized data only. It must not call RailKit or perform network I/O.

## 2. Graph representation

Given ordered stops:

`A(0) → B(1) → C(2) → D(3) → E(4) → F(5)`

Create a directed acyclic graph. A checked segment A→D becomes an edge from node 0 to node 3. Edges always move forward.

An edge is identified by:
`(train_number, journey_date, from_station, to_station, class, quota)`

Do not create an edge simply because two stations are consecutive. Create an edge only after a valid availability query response has been normalized.

## 3. Candidate path rules

A valid path:
- starts at requested source;
- ends at requested destination;
- is contiguous (`edge[i].to == edge[i+1].from`);
- advances in route order;
- uses same train number;
- uses same journey date;
- uses same class;
- uses one quota (the combination's: GN or TQ) — never mixed;
- contains 1–4 segments;
- contains no duplicate or backward station traversal.

A path is a **candidate** if its segments have interpretable results. Whether it is **eligible** depends on user filters:
- confirmed/available only;
- allow RAC;
- allow WL;
- include not-available/unknown (normally false; diagnostic only).

Default MVP recommendation: include `AVAILABLE` and `CONFIRMED`; allow RAC and WL through explicit filters. Never treat `UNKNOWN` as usable.

## 4. Path enumeration

Because station order is a DAG, a bounded depth-first search is simple and reliable for a maximum depth of four.

Pseudo-code:

```python
def find_paths(source, destination, outgoing_edges, max_segments=4):
    results = []

    def dfs(node, path):
        if node == destination:
            if path:
                results.append(path.copy())
            return

        if len(path) >= max_segments:
            return

        for edge in outgoing_edges.get(node, []):
            if edge.to_index <= node:
                continue
            if path and path[-1].to_station != edge.from_station:
                continue
            path.append(edge)
            dfs(edge.to_index, path)
            path.pop()

    dfs(source_index, [])
    return results
```

Production implementation must add:
- deterministic edge ordering;
- maximum number of paths returned;
- pruning of ineligible edges;
- duplicate path elimination;
- cancellation/deadline handling;
- unit tests for same-stop and repeated-station edge cases.

## 5. Ranking policy

Use a transparent lexicographic ranking rather than an unexplained weighted score.

First apply hard eligibility filters. Then sort by a tuple such as:

1. `status_tier` (best tier first)
2. `provider_prediction_score` (higher first; missing last)
3. `segment_count` (fewer first)
4. `total_fare` (lower first, only when complete)
5. `freshness_seconds` (newer first)
6. deterministic path key (stable tie-breaker)

Suggested status tier:
- Tier 0: all segments `CONFIRMED` or `AVAILABLE`.
- Tier 1: no WL; at least one RAC.
- Tier 2: one or more WL, only when WL is allowed.
- Excluded: `NOT_AVAILABLE` or `UNKNOWN` segments for normal recommendations.

Important product decision: status tier should outrank provider prediction. A high predicted percentage must not cause a WL path to outrank an all-confirmed path.

For mixed segments:
- `path_prediction_min`: minimum available segment prediction.
- `path_prediction_mean`: mean of available predictions, only as a descriptive summary.
- `prediction_coverage`: number of segments with prediction / total segments.

Do not multiply segment probabilities to claim a mathematically valid whole-path probability. Correlation and provider methodology are unknown. Do not display a path-level probability in MVP unless separately validated and clearly labelled as a heuristic. Prefer showing each segment's provider prediction.

## 6. Availability query planner

The number of forward station pairs for N route stops is N(N−1)/2. Querying every pair for every class can exhaust provider plans quickly.

Use staged, budgeted discovery:

### Stage 0 — Direct segment
Query source → destination for each selected class.

### Stage 1 — Two-segment candidates
For every intermediate stop M:
- source → M
- M → destination

Reuse cached responses and deduplicate requests.

### Stage 2 — Three-segment candidates
Explore promising pairs of intermediate stops M1, M2:
- source → M1
- M1 → M2
- M2 → destination

### Stage 3 — Four-segment candidates
Explore combinations of three intermediate stops, bounded by request budget and candidate count.

### Pruning
- Do not query segments outside the requested source/destination interval.
- Do not query invalid route pairs.
- Reuse identical availability results across candidate paths.
- If a required edge is already `NOT_AVAILABLE`, avoid expanding paths that require it.
- Do not treat failed/unqueried edges as unavailable.
- Stop when budget or deadline is reached and mark search partial.

A breadth-first or priority-based planner may be used. The exact query ordering must be documented and tested. Favor direct and shorter-segment combinations first.

### 6b. Dominated split tickets (docs/08 D-34)

If a segment a → b is CONFIRMED/AVAILABLE, no combination splits a → b into two or more smaller
tickets (same train run, class and quota). Such candidates are pruned before their remaining
segments are requested, and such paths are never returned. RAC/waitlist segments, and
predictions of any value, never prune anything.

### 6a. Implemented scheduling across combinations (docs/08 D-27)

Each query slot goes to the active train × class × quota combination with the smallest key
*(depth, queries at that depth, result quality, round-robin distance from a persistent cursor)*:

1. every combination's **direct ticket** first;
2. then 2-ticket, then 3-ticket, then 4-ticket alternatives — a level is finished across all
   combinations before any combination starts the next one;
3. within a level the budget is shared equally; combinations with no complete path go first in
   each round, then those whose best path includes waitlist, then RAC;
4. a solved (all confirmed/available) or exhausted combination stops, and its share goes to the rest.

Consequences: with budget B ≥ number of combinations N, every direct ticket is checked; with B < N,
exactly B distinct combinations get their direct check (GN and TQ alternate) and the rest are
reported as not reached (`coverage.combinations_not_reached`), never as unavailable.
`POST /journeys/preview` shows N and the budget before a search starts.

## 7. API budget controls

The server owns:
- maximum availability calls per search;
- maximum concurrent provider requests;
- per-user rate limit;
- per-provider rate limit;
- daily/monthly provider budget guard;
- cache TTL.

Client may request a search depth, but server clamps it to policy. A client must never be able to increase the provider budget beyond configured limits.

`SEARCH_MAX_AVAILABILITY_REQUESTS` caps provider **attempts**, retries included (docs/08 D-28).

Return:
- `availability_requests_planned`
- `availability_requests_made` (attempts, retries included), `availability_checks_made` (logical),
  `availability_retries`, `availability_retries_refused`, `combinations_not_reached`
- `cache_hits`
- `search_completeness`
- `incomplete_reason`
- `trains_evaluated`
- `segments_checked`

## 8. Caching and request deduplication

Cache key:
`railkit:availability:{train}:{journey_date}:{from}:{to}:{class}:GN`

Use short TTL for availability (initial configurable default e.g. 60–180 seconds, to be calibrated against RailKit's actual freshness/terms). Do not assume this TTL is authorized: verify RailKit's caching rules.

Use Redis single-flight/distributed lock to prevent simultaneous identical misses from triggering duplicate provider calls.

Train route cache can have a longer TTL because schedule data changes less frequently, but must be invalidated/expired according to provider policy.

## 8a. Reservation quotas (docs/08 D-20…D-25)

- Every **train × class × quota** is its own planner combination, graph (`GraphKey` includes the
  quota) and set of paths. Combination ids are quota-major (GN first); the planner's round-robin
  order interleaves GN and TQ so neither quota starves the other (D-27).
- A TQ combination is created only when `QuotaEligibilityService` says the booking window is open
  (`OPEN`, `OPENING_PASSED`); `GN` is always `NOT_APPLICABLE`. Skipped combinations spend no budget,
  are counted in `coverage.combinations_not_queried` and make the search
  `PARTIAL_QUOTA_NOT_QUERIED` (never "no path exists").
- The window is anchored to the train's **origin date** (`train_start_date`), not the boarding date.
- The per-search budget, deadline and provider quota guard are shared by all quotas; budget refusals
  are reported per combination exactly as before.
- Cache keys and single-flight keys already contain the quota
  (`availability:{provider}:{train}:{start}:{provider_date}:{from}:{to}:{class}:{quota}`), so a GN answer
  is never reused for TQ. The planner never asks for the same edge twice within a combination.
- Ranking is unchanged (§5). The quota only enters the final stable tie-breaker (GN, TQ order).
  Consequence: a direct Tatkal ticket outranks a 2-ticket General combination with
  the same status tier, because fewer tickets beats lower fare.

## 9. Worked example

Route:
`TIR → SRR → TCR → AWY → ERS → KTYM → QLN → TVC`

Suppose queried edges:
- TIR→SRR: CONFIRMED
- SRR→ERS: AVAILABLE
- ERS→TVC: RAC
- TIR→TCR: WAITLIST
- TCR→ERS: CONFIRMED
- ERS→TVC: RAC
- KTYM→TVC: UNKNOWN

Valid path:
`TIR→SRR → SRR→ERS → ERS→TVC` (3 segments)

Another valid path:
`TIR→TCR → TCR→ERS → ERS→TVC` (3 segments)

If WL is disabled, the second path is excluded. If RAC is allowed, first path remains eligible. The repeated ERS→TVC edge is queried once and reused.

## 10. Required unit tests

- Direct path.
- Two-edge path.
- Four-edge path.
- Five-edge path rejected.
- Disconnected edges.
- Backward edge rejected.
- Different train IDs cannot combine.
- Different classes cannot combine.
- Different dates cannot combine.
- Different quotas cannot combine (a TQ graph rejects GN edges).
- WL excluded when filter false.
- RAC excluded when filter false.
- Unknown never treated as available.
- Prediction absent.
- Prediction malformed/out of range.
- Stable ranking ties.
- Budget exhaustion yields partial result.
- Provider error does not become `NOT_AVAILABLE`.
