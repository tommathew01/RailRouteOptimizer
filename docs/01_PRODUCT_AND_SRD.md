# 01 — Product Definition and Software Requirements Document

## 1. Product overview

**RailRoute Optimizer** helps a passenger discover whether a journey from origin to destination can be completed by booking multiple consecutive reservation segments on the **same train**, when a direct reservation is unavailable or undesirable.

Example: a passenger wants Tirur (`TIR`) to Thiruvananthapuram Central (`TVC`). The application identifies one train that serves both stations, obtains its ordered route, checks selected station-to-station availability segments, and finds valid combinations such as:

`TIR → SRR` + `SRR → TCR` + `TCR → TVC`

The output is a ranked set of candidate booking plans. Each edge is a separate reservation query and potentially a separate ticket/PNR. The product does not book tickets.

## 2. Problem statement

Railway availability is specific to a train, journey date, source station, destination station, class and quota. A direct source-destination query may show no suitable inventory even though shorter or overlapping reservation segments on the same train have different availability.

Manually finding a combination requires repeatedly searching the same train and date across intermediate station pairs. RailRoute automates the discovery, comparison and explanation of these combinations.

## 3. Product goals

1. Accept an origin, destination, date and one or more travel classes.
2. Discover trains serving the requested journey.
3. retrieve and validate the train's ordered station route.
4. Check availability for candidate segments on the same train.
5. Find valid paths containing no more than four ticket segments.
6. Show actual current availability separately from RailKit's optional prediction.
7. Rank combinations transparently and explain why one ranks above another.
8. Respect provider request limits and disclose incomplete search coverage.
9. Provide booking guidance or authorized booking-channel links without handling credentials or payment.

## 4. Non-goals for MVP

- Automated IRCTC login, ticket booking, payment or cancellation.
- Storing IRCTC passwords, OTPs or payment credentials.
- Inter-train or multi-modal connections.
- Cross-train transfer optimization.
- Custom machine-learning confirmation model.
- A promise that provider predictions are accurate or guaranteed.
- Passenger identity collection.
- Passenger count input. Availability checks are single-ticket checks as agreed; do not infer party capacity.
- Treating separate tickets as one through-ticket or claiming break-of-journey rights.
- Guaranteeing that a set of sequential bookings will all succeed.

## 5. Target users and primary user journey

### Primary user
A passenger who has a preferred train and wants to find alternative segment combinations when the direct ticket is unavailable.

### Main journey
1. User opens the responsive web app.
2. Selects source and destination stations.
3. Selects journey date.
4. Selects one or more classes.
5. Quota: General (`GN`) by default; Tatkal (`TQ`) is selectable and
   searched separately once its booking window opens (added 2026-11-15, docs/08 D-20).
6. User submits search.
7. Backend discovers eligible trains and obtains route data.
8. Availability planner queries candidate segments within a configurable request budget.
9. Optimizer finds paths from source to destination with 1–4 segments.
10. UI displays ranked paths, each segment's status, prediction (if supplied), fare (if supplied), timestamps and search completeness.
11. User follows booking guidance and completes each booking independently on an authorized platform.

## 6. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-001 | Search stations by name/code and return disambiguated station codes | Must |
| FR-002 | Accept source, destination, journey date and one or more classes | Must |
| FR-003 | Let the user select quotas (GN default, TQ); validate and order them server-side; never substitute an unsupported quota | Must |
| FR-004 | Discover trains between source and destination for requested date | Must |
| FR-005 | Retrieve complete ordered train route and stop metadata | Must |
| FR-006 | Validate source and destination occur in correct order in train route | Must |
| FR-007 | Generate candidate forward-only segments between route stops | Must |
| FR-008 | Query RailKit availability for a segment, train, date, class and quota; query TQ only after its booking window (origin date − 1 day, 10:00 AC / 11:00 non-AC IST) opens | Must |
| FR-009 | Normalize provider statuses while preserving raw status and payload | Must |
| FR-010 | Preserve RailKit prediction text and percentage as separate optional fields | Must |
| FR-011 | Find valid source-to-destination paths of at most four segments | Must |
| FR-012 | Never mix trains, journey dates, classes or quotas within one path | Must |
| FR-013 | Rank paths using actual availability first and provider prediction as a secondary factor | Must |
| FR-014 | Display per-segment status, raw status, prediction, fare and checked timestamp when present | Must |
| FR-015 | Show whether search was complete, partial or stopped by budget/provider error | Must |
| FR-016 | Cache and deduplicate identical availability requests within safe TTL rules | Must |
| FR-017 | Handle timeouts, 401/403, 404, 429, 5xx and malformed payloads | Must |
| FR-018 | Provide search results retrieval by search ID | Should |
| FR-019 | Store search and availability observations for audit and product analytics | Should |
| FR-020 | Provide authorized booking-channel links or instructions | Should |
| FR-021 | Allow filters for confirmed-only, include RAC, include WL and class | Should |
| FR-022 | Display fare total only when each required segment fare is available and comparable | Should |

## 7. Availability vocabulary

Internal normalized status enum:

- `AVAILABLE` — provider indicates positive available inventory, such as AVL/AVAILABLE.
- `CONFIRMED` — provider explicitly returns confirmed status (`CNF`).
- `RAC` — provider explicitly returns RAC.
- `WAITLIST` — provider explicitly returns a waitlist category (GNWL/RLWL/PQWL/etc.).
- `NOT_AVAILABLE` — provider explicitly indicates no availability / closed / unavailable.
- `UNKNOWN` — missing, ambiguous, malformed or unsupported response.

Do not collapse `AVAILABLE` and `CONFIRMED` unless the provider contract explicitly establishes equivalence. Preserve:
- `raw_status`
- `availability_text`
- `waitlist_type` where parseable
- `waitlist_number` where parseable
- `available_count` where explicitly supplied
- `can_book` where explicitly supplied, but do not interpret `can_book=true` as confirmed.

## 8. Prediction requirements

RailKit may return fields such as `prediction` and `predictionPercentage` in an availability record.

Rules:
1. Preserve exact provider text in `prediction_text`.
2. Parse numeric percentage into `prediction_percentage` only when the value is valid and within 0–100.
3. Store provider name and observation timestamp.
4. Do not manufacture a prediction if absent.
5. Do not treat prediction as actual status.
6. UI label must say **Provider estimate** or **RailKit prediction**, not “confirmation guarantee”.
7. Ranking may use prediction only after hard status eligibility rules have been applied.
8. A missing prediction must not cause a valid segment to be discarded.
9. No custom ML model is in MVP.

## 9. Non-functional requirements

- Security: API keys only server-side; HTTPS; secrets via environment/secret manager.
- Reliability: partial provider failures must not erase successful segment results.
- Performance: return useful partial progress/results when practical; do not promise a fixed end-to-end SLA until provider latency and quotas are measured.
- Scalability: asynchronous I/O, bounded concurrency, Redis cache and per-provider rate limiting.
- Maintainability: provider adapter isolated from domain and optimization modules.
- Observability: structured logs, trace/search IDs, latency, error category and request usage.
- Privacy: no passenger names, IDs, PNRs or payment data required for search.
- Accessibility: keyboard navigable, semantic labels, status not communicated by colour alone.
- Localization: store timestamps in UTC with timezone metadata; display railway journey times in Asia/Kolkata.

## 10. Business rules and user-facing disclaimers

- A path is a sequence of separate reservations, not a single ticket.
- Each segment may produce a different PNR, coach, berth or seat.
- The availability can change between checking and booking.
- Booking the first segment does not reserve subsequent segments.
- A segment may be bookable but waitlisted; bookability is not confirmation.
- The product does not guarantee prediction accuracy or final booking success.
- Users must verify all segment details on the authorized booking platform before payment.
- The product is independent unless a formal affiliation is separately established. Do not use Indian Railways/IRCTC logos or imply endorsement without permission.

## 11. MVP acceptance criteria

The MVP is accepted when:
1. User can submit a valid journey search.
2. Trains are returned and route order is verified.
3. At least one class can be queried through RailKit.
4. Segment results normalize correctly for AVL/CNF/RAC/WL/unavailable/unknown.
5. Prediction text and percentage are preserved independently.
6. Optimizer returns only contiguous forward paths, 1–4 segments.
7. Every path uses the same train/date/class/quota.
8. Ranking is deterministic for identical inputs.
9. API budget and partial-search metadata are enforced and visible.
10. Tests cover route validation, path generation, status mapping, missing prediction and provider failures.
11. RailKit key is not exposed in browser bundles, API responses or logs.
12. The UI clearly warns that each segment must be booked separately.
