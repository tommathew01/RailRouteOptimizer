# 05 — Internal REST API Specification

Base path: `/api/v1`  
Content type: `application/json`  
Date input: ISO `YYYY-MM-DD` at our API boundary. Convert to RailKit's required format in the adapter after contract verification.  
Quota: server-enforced `GN`.

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

Quota is not accepted from the client in MVP; backend uses `GN`.

Response:
```json
{
  "train_number": "12345",
  "source": "TIR",
  "destination": "SRR",
  "journey_date": "2026-11-20",
  "travel_class": "3A",
  "quota": "GN",
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
  "max_segments": 4
}
```

Server policy clamps `max_segments` to 4 and enforces GN. Passenger count is not accepted. Provider request budget is server-side configuration.

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
