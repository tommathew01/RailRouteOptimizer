# 03 — Railway Domain Model and Business Rules

## 1. Core entities

### Station
- `code`: canonical railway station code.
- `name`: display name.
- Optional alternate names, city and metadata.
- Station codes, not names, are used for route identity.

### Train
- `train_number`: canonical train number string.
- `train_name`.
- Operating days and metadata where available.

### TrainStop
- `train_number`
- `sequence_index`
- `station_code`
- `arrival_time`
- `departure_time`
- `day_offset` (important for trains crossing midnight)
- `halt_minutes` if known
- `is_stoppage` / intermediate point if provider distinguishes them.

The route must be ordered. Do not sort by station name or time string.

### Segment
A candidate reservation request from one train stop to a later train stop:
- train
- journey origin date
- from station
- to station
- from route index
- to route index
- class
- quota (`GN`)

A segment is valid only if `from_index < to_index`.

### AvailabilityObservation
An immutable observation of the provider's result at a particular time:
- normalized status
- raw status
- availability text
- waitlist category and number where parseable
- available count if returned
- can-book flag if returned
- provider prediction text and percentage
- fare if returned
- provider name
- checked timestamp
- sanitized raw payload

### Recommendation
A sequence of 1–4 segment observations that forms a contiguous path from requested source to destination, within one train, date, class and quota.

## 2. Journey date semantics

Use the **train's originating journey date** as the canonical journey date unless RailKit's contract specifies otherwise. A train crossing midnight may reach a later station on the next calendar date. Store:
- journey start date
- station-level day offset
- computed local arrival/departure date-time where route data supports it.

Do not silently change the date parameter for a segment based on the intermediate station's calendar date. Verify with RailKit whether its availability endpoint expects originating journey date. This is a provider contract test.

## 3. Route validation

Before checking segments:
1. Ensure source and destination exist in route.
2. Ensure source index is less than destination index.
3. Ensure route sequence is complete enough to represent the requested corridor.
4. Ensure train is scheduled to serve both stations on the selected journey date.
5. Do not create an edge for a station pair absent from the route.
6. If route data is incomplete, mark train as `ROUTE_UNVERIFIED` and do not generate recommendations.

## 4. Class and quota rules

- User selects one or more classes supported by RailKit and train.
- Each class is optimized independently.
- Do not mix classes within one recommendation.
- General quota is fixed to `GN` in MVP.
- Backend enforces quota even if a client submits another value.
- Unsupported class should return a validation error, not be silently dropped.
- Train-specific class support must be checked where available.

## 5. Passenger count rule

No passenger count is requested or stored. Each availability call represents the provider's ordinary single-ticket availability response. UI must not claim that the result accommodates a group or multiple passengers.

## 6. Status normalization

Suggested mapping (must be verified against actual provider payload variants):

| Provider representation | Internal status |
|---|---|
| `CNF`, `CONFIRMED` | `CONFIRMED` |
| `AVL`, `AVAILABLE`, `AVAILABLE-0012` | `AVAILABLE` |
| `RAC`, `RAC 2` | `RAC` |
| `GNWL`, `RLWL`, `PQWL`, `TQWL`, etc. | `WAITLIST` |
| `NOT AVAILABLE`, `REGRET`, `CLOSED` | `NOT_AVAILABLE` |
| null, unrecognized or malformed | `UNKNOWN` |

Preserve exact provider text. Never parse status solely from a prediction string.

`canBook` is a separate boolean. A waitlisted ticket can be bookable; this does not make it confirmed or available.

## 7. Prediction semantics

- Provider estimate is an independent optional field.
- Keep `prediction_text` exactly as supplied.
- Parse percentage only from a numeric provider field or carefully validated text fallback.
- Range 0–100 inclusive.
- Invalid/out-of-range values become null and are logged as a schema anomaly.
- Prediction absence is normal.
- Prediction never changes current status.
- Do not call it a model trained by RailRoute.
- UI must attribute it to RailKit.

## 8. Fare semantics

- Fare may be returned by availability or a separate fare endpoint.
- Fare is optional and segment-specific.
- Total path fare is the sum only if every segment has a valid comparable fare in the same currency and fare basis.
- Otherwise display “Fare unavailable/incomplete”, not a partial sum labelled as total.
- Confirm whether fare API calls consume additional provider quota before enabling them by default.

## 9. Separate-ticket constraints

A path of three segments is three separate reservation attempts and may result in three PNRs. It may have:
- different coach/berth assignments;
- different reservation statuses;
- different cancellation/refund implications;
- no guarantee of continuous accommodation;
- risk that a later segment becomes unavailable after an earlier segment is booked.

Never imply that multiple segment tickets are equivalent to one through ticket, or that they automatically grant break-of-journey privileges.

## 10. Search completeness vocabulary

- `COMPLETE`: all candidate queries defined by the configured planner and budget completed.
- `PARTIAL_BUDGET`: budget exhausted before planner completed.
- `PARTIAL_PROVIDER_ERRORS`: one or more required provider queries failed.
- `PARTIAL_TIMEOUT`: overall deadline reached.
- `NO_PATH_FOUND`: planner completed its defined search but no eligible path exists.
- `NO_PATH_FOUND_PARTIAL`: no path among checked edges, but search was incomplete.

Do not claim “no tickets exist” when the search was partial. Say “No combination found in the segments checked.”
