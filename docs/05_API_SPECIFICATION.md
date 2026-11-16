# 05 — Internal REST API Specification

Base path: `/api/v1`  
Content type: `application/json`  
Date input: ISO `YYYY-MM-DD` at our API boundary. Convert to RailKit's required format in the adapter after contract verification.  
Quota: General (`GN`) by default; Tatkal (`TQ`) on request, each searched
separately and only once its booking window is open (§9, docs/08 D-20…D-25).

## 1. Station search

`GET /api/v1/stations/search?q=tirur`

Response:
```json
{
  "items": [
    {"code": "TIR", "name": "Tirur", "city": "Tirur"}
  ]
}
```

Return exact station codes and enough metadata to disambiguate duplicate names.

## 2. Train search

`POST /api/v1/trains/search`

Request:
```json
{
  "source": "TIR",
  "destination": "TVC",
  "journey_date": "2026-11-20"
}
```

Response:
```json
{
  "trains": [
    {
      "train_number": "12345",
      "train_name": "Example Express",
      "source": "TIR",
      "destination": "TVC",
      "departure_time": "18:00",
      "arrival_time": "07:30",
      "running_days": "1111111",
      "classes": ["SL", "3A", "2A"]
    }
  ]
}
```

Fields are illustrative; map only values actually returned by RailKit.

## 3. Train route

`GET /api/v1/trains/{train_number}/route`

Response:
```json
{
  "train_number": "12345",
  "stops": [
    {
      "sequence": 0,
      "station_code": "TIR",
      "station_name": "Tirur",
      "arrival": null,
      "departure": "18:00",
      "day_offset": 0
    }
  ],
  "route_verified": true
}
```

## 4. Individual segment availability

`POST /api/v1/availability/check`

Request:
```json
{
  "train_number": "12345",
  "source": "TIR",
  "destination": "SRR",
  "journey_date": "2026-11-20",
  "travel_class": "3A"
}
```

Optional `"quota": "GN" | "TQ"` (default and `null` → `GN`). TQ is only sent to the provider
when the booking window is open; otherwise the response has `queried: false`, `availability: null` and an
`eligibility` block (§9). An unknown code is a 400.

Response:
```json
{
  "train_number": "12345",
  "source": "TIR",
  "destination": "SRR",
  "journey_date": "2026-11-20",
  "travel_class": "3A",
  "quota": "GN",
  "quota_label": "General",
  "queried": true,
  "eligibility": { "quota": "GN", "state": "NOT_APPLICABLE", "queryable": true, "...": "§9" },
  "availability": {
    "status": "WAITLIST",
    "availability_text": "WL 5",
    "raw_status": "GNWL5/WL5",
    "waitlist_type": "GNWL",
    "waitlist_number": 5,
    "available_count": null,
    "can_book": true
  },
  "prediction": {
    "provider": "RAILKIT",
    "text": "75% Chance",
    "percentage": 75
  },
  "fare": null,
  "provider_checked_at": "2026-11-07T10:00:00Z",
  "cached": false
}
```

Prediction and fare objects may be null. A missing prediction is not an error.

## 5. Optimize journey

`POST /api/v1/journeys/optimize`

Request:
```json
{
  "source": "TIR",
  "destination": "TVC",
  "journey_date": "2026-11-20",
  "classes": ["3A", "SL"],
  "filters": {
    "allow_rac": true,
    "allow_waitlist": false
  },
  "max_segments": 4,
  "quotas": ["GN", "TQ"]
}
```

Server policy clamps `max_segments` to 4. `quotas` defaults to `["GN"]` and is returned in canonical
order (GN, TQ); the deprecated single `quota` field is ignored with a note. Passenger count is not
accepted. Provider request budget is server-side configuration and is shared by all quotas.

For asynchronous execution:
`202 Accepted`
```json
{
  "search_id": "uuid",
  "status": "QUEUED",
  "status_url": "/api/v1/journeys/uuid"
}
```

For completed search:
```json
{
  "search_id": "uuid",
  "status": "COMPLETED",
  "search_completeness": "PARTIAL_BUDGET",
  "incomplete_reason": "AVAILABILITY_REQUEST_BUDGET_REACHED",
  "coverage": {
    "trains_evaluated": 3,
    "availability_requests_planned": 80,
    "availability_requests_made": 50,
    "cache_hits": 12,
    "segments_checked": 38
  },
  "recommendations": [
    {
      "rank": 1,
      "train_number": "12345",
      "train_name": "Example Express",
      "travel_class": "3A",
      "quota": "GN",
      "quota_label": "General",
      "segment_count": 3,
      "status_tier": 0,
      "segments": [
        {
          "source": "TIR",
          "destination": "SRR",
          "status": "CONFIRMED",
          "availability_text": "CNF",
          "prediction": {"provider": "RAILKIT", "text": "92% Chance", "percentage": 92},
          "fare": null,
          "checked_at": "2026-11-07T10:00:00Z"
        }
      ],
      "total_fare": null,
      "fare_complete": false
    }
  ],
  "warnings": [
    "Each segment is a separate reservation and may create a separate PNR.",
    "Availability can change before booking."
  ]
}
```

## 6. Retrieve search

`GET /api/v1/journeys/{search_id}`

Returns queued/running/completed/failed state and current progress or final result.

## 7. Error format

```json
{
  "error": {
    "code": "INVALID_STATION",
    "message": "The supplied station code is not recognized.",
    "request_id": "uuid"
  }
}
```

Suggested HTTP status:
- 400 invalid request or invalid station/date/class.
- 401 unauthenticated (once user accounts enabled).
- 404 search/train not found.
- 409 invalid journey route or conflicting state.
- 422 semantically invalid class/route.
- 429 app/provider usage limit.
- 502 provider returned invalid/upstream response.
- 503 provider unavailable.
- 504 provider timeout.

Never return RailKit API key, provider auth headers, raw exception trace or secrets.

## 8. API compatibility

- Version all public routes.
- Use Pydantic request/response models.
- Generate OpenAPI.
- Add contract tests.
- Do not expose RailKit response JSON as the public API contract.

## 9. Reservation quotas (GN, TQ)

All changes are additive; a General-only client sees the same behaviour as before.

| Where | Field | Meaning |
|---|---|---|
| `POST /journeys/optimize` | `quotas: ["GN" \| "TQ"]` (1–2, default `["GN"]`; any other code, including `PT`, is a 400) | Each quota is a separate search space; one recommendation never mixes quotas. If **none** of the selected quotas is supported by the provider → `422 QUOTA_NOT_SUPPORTED` before any provider call. |
| Search result | `request.quotas` (`request.quota` = first, deprecated) | Echo. |
| Search result | `recommendations[].quota`, `quota_label` | The quota of every segment of that recommendation. |
| Search result | `trains[].classes[]` → one row per class × quota with `quota`, `queried`, `eligibility` | New states `NOT_YET_OPEN`, `QUOTA_NOT_SUPPORTED`, `NOT_QUERIED`. Never `NOT_AVAILABLE`. |
| Search result | `quotas[]` (`QuotaSummary`) | `provider_supported`, `queried`, `combinations_eligible`, `combinations_not_queried`, `next_opening_at`, `not_queried[]` groups with a message, `recommendations`. |
| Search result | `coverage.combinations_not_queried` | Offered train × class × quota combinations deliberately not queried. |
| Search result | `search_completeness = PARTIAL_QUOTA_NOT_QUERIED`, `incomplete_reason = QUOTA_NOT_QUERIED` | Some selected quota was not checked (budget, timeout and provider reasons take precedence). With no recommendations: `NO_PATH_FOUND_PARTIAL`. |
| `POST /availability/check` | `quota`, response `quota_label`, `queried`, `eligibility`; `availability`/`checked_at` null when not queried | Single segment, one quota. |
| `GET /meta` | `quotas[]` (`code`, `label`, `default`, `provider_supported`, `opening_rule`, `note`), `supported_classes[].category` (`AC`/`NON_AC`/null) | For rendering the selector and the opening rule. `quota.editable` is now `true`. |

`eligibility` (`QuotaEligibility`):

```json
{
  "quota": "TQ",
  "state": "NOT_YET_OPEN",
  "queryable": false,
  "class_category": "AC",
  "train_origin_date": "2026-11-20",
  "opens_at": "2026-11-19T10:00:00+05:30",
  "message": "Tatkal (TQ) booking for class 3A opens on 19 Nov 2026 at 10:00 IST (the train leaves its origin station on 20 Nov 2026). Not checked yet — search again after it opens."
}
```

| `state` | Queried? | Meaning |
|---|---|---|
| `NOT_APPLICABLE` | yes | No booking window (General). |
| `NOT_YET_OPEN` | no | Opens on a later IST calendar day. |
| `OPENS_TODAY` | no | Opens later today. |
| `OPEN` | yes | Opened; the train has not reached its origin date. |
| `OPENING_PASSED` | yes | Opening day is over; booking may stay open until charting, so the provider is asked. |
| `JOURNEY_DATE_PASSED` | no | Boarding date before today (IST). |
| `CLASS_CATEGORY_UNKNOWN` | no | Class has no AC/non-AC mapping (`VC`, `CH`, `HS`). |
| `UNDETERMINED` | no | Origin or journey date missing/inconsistent. |
| `PROVIDER_UNSUPPORTED` | no | The provider does not support this quota (e.g. Tatkal disabled via `RAILKIT_SUPPORTED_QUOTAS`). |

Not-queried quotas are never re-queried automatically; the client searches again after `opens_at`.

## 10. Budget accounting, limits and search preview (docs/08 D-27…D-30)

All additions have defaults, so stored snapshots and older clients keep working.

| Where | Field | Meaning |
|---|---|---|
| `POST /journeys/optimize`, `/journeys/preview` | `classes` (≤ `limits.max_classes_per_search`, default 3), `train_numbers` (≤ `limits.max_trains_per_search`, default 5) | Above a limit: `400 TOO_MANY_CLASSES` / `TOO_MANY_TRAINS` with `details.max_*`, before any provider call. Selections are never truncated. |
| Search result | `coverage.availability_requests_made` | Provider availability **attempts** charged to the budget, retries included. |
| Search result | `coverage.availability_checks_made`, `availability_retries`, `availability_retries_refused` | Logical checks sent to the provider (cache hits excluded); retry attempts included above; failed checks not retried because the budget was used up (they stay "not checked"). |
| Search result | `coverage.request_budget` | `SEARCH_MAX_AVAILABILITY_REQUESTS`: attempts allowed per search. |
| Search result | `coverage.combinations_not_reached` | Queryable combinations that got no check at all (budget/deadline/provider stop). `0` whenever the budget covers every direct check. |
| Search result | `trains[].classes[].segments_queried` | Segment answers for that combination (cache hits included). |
| `GET /meta` | `limits.default_trains_selected`, `limits.max_classes_per_search` | Mirrored by the UI; the server stays authoritative. |

`POST /api/v1/journeys/preview` takes the optimize request body and returns what a search started
now would check — with **no** availability request (it loads only the selected trains' routes,
which the search needs anyway). Same validation and errors as optimize.

```json
{
  "data_mode": "LIVE",
  "request_budget": 30,
  "max_segments": 4,
  "trains_selected": 3,
  "trains_evaluated": 3,
  "combinations": 12,
  "combinations_not_queried": 0,
  "classes_not_offered": 0,
  "requests_per_combination": 2.5,
  "covers_direct_checks": true,
  "planned": [{"train_number": "12076", "travel_class": "3A", "quota": "GN"}],
  "quotas": [{"quota": "GN", "quota_label": "General", "combinations": 6,
              "combinations_not_queried": 0, "next_opening_at": null, "notes": []}],
  "trains": [{"train_number": "12076", "train_name": "Example Express",
              "evaluation": "EVALUATED", "combinations": 4}],
  "explanation": [
    "12 train/class/quota combinations share a budget of 30 provider requests per search. Each gets its direct-ticket check first (12 requests).",
    "The remaining 18 requests look for split-ticket alternatives (2, then 3, then 4 tickets), shared fairly. Each extra train or class adds combinations and leaves less depth for each."
  ]
}
```
