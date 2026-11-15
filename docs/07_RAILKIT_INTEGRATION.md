# 07 — RailKit Provider Integration Specification

## 1. Integration strategy

Use RailKit's REST API directly from FastAPI using `httpx`. Do not add a Node.js microservice solely because RailKit also publishes a Node SDK.

Create:
- `RailKitHttpClient`: low-level HTTP, headers, timeout, retries.
- `RailKitProvider`: implements the internal `RailwayProvider` interface.
- `RailKitMapper`: maps provider payloads to domain models.
- Pydantic provider DTOs for validation where useful.

All RailKit-specific code stays under `app/integrations/railkit/`.

## 2. Published endpoint references

RailKit documentation reviewed:
- Main docs: https://railkit.in/docs
- Seat availability: https://railkit.in/docs/seat-availability
- Train search: https://railkit.in/docs/train-search

Published REST route patterns currently shown:
- Train search: `GET /api/v1/trains/between/{from}/{to}?date=DD-MM-YYYY`
- Train information: `GET /api/v1/trains/{trainNumber}/info`
- Seat availability: `GET /api/v1/seats/{trainNo}/{from}/{to}/{date}/{coach}/{quota}`
- Fare: `GET /api/v1/fare/{trainNo}/{date}/{from}/{to}/{class}/{quota}`
- Station search: `GET /api/v1/stations/search?name=...`

Authentication: API key header shown as `x-api-key`. Base URL shown in provider examples: `https://api.railkit.in`.

**Contract warning:** Treat these as documentation-derived current references, not immutable guarantees. Verify in the RailKit account/playground and current docs before coding endpoint assumptions.

## 3. Date conversion

Our public API accepts ISO `YYYY-MM-DD`. RailKit docs currently show `DD-MM-YYYY` for train search and seat availability examples. Implement one tested conversion helper and use it consistently. Do not format dates independently in different services.

## 4. Availability response fields

Published seat availability example includes:
- `success`
- `data.train`
- `data.fare`
- `data.availability[]`
- availability item fields such as `date`, `status`, `availabilityText`, `rawStatus`, `prediction`, `predictionPercentage`, `canBook`.

The example illustrates a `WAITLIST` status with a waitlist text and a provider prediction. Therefore:
- status is current/returned availability classification;
- prediction is a separate provider estimate;
- `canBook` is not equivalent to confirmed status.

Do not assume every response contains all fields. Use nullable fields and schema validation.

## 5. Internal provider interface

```python
from typing import Protocol

class RailwayProvider(Protocol):
    async def search_trains(self, source: str, destination: str, journey_date: str): ...
    async def get_train_info(self, train_number: str): ...
    async def get_availability(
        self, train_number: str, source: str, destination: str,
        journey_date: str, travel_class: str, quota: str
    ): ...
    async def search_stations(self, query: str): ...
```

The optimization engine receives domain DTOs, never provider DTOs.

## 6. HTTP client requirements

- Shared `httpx.AsyncClient` with connection pooling.
- Configurable connect/read/write/pool timeouts.
- `x-api-key` and `accept: application/json` headers.
- Bounded retry for idempotent GET on transient network errors and selected 5xx.
- Respect 429; use Retry-After if supplied, otherwise bounded backoff.
- Do not retry 400/401/403/404 blindly.
- Validate HTTP status and JSON envelope.
- Validate `success` field if present.
- Redact API key in logs.
- Record latency and provider request count.
- Use semaphore for bounded concurrency.
- Close client on application shutdown.

## 7. Prediction mapping

Map:
- `prediction` → `prediction_text`
- `predictionPercentage` → `prediction_percentage`

Parsing:
- Preserve provider text exactly.
- Convert numeric string/int/float only if finite and 0 <= value <= 100.
- If absent, null.
- If invalid, null plus schema warning.
- Do not derive a percentage from ambiguous natural language unless the parser is explicitly tested.
- Keep provider attribution `RAILKIT`.

## 8. Fare mapping

Map `data.fare.totalFare` only if numeric and currency is known/assumed by verified provider contract. Keep fare null otherwise. A path total is valid only when all segment fares are available on a comparable basis.

## 9. Required live contract checks

Before declaring RailKit integration complete, test with a real account:
1. API key authentication and exact header.
2. Train search date format.
3. Train info route structure and station ordering.
4. Seat availability for a direct segment.
5. Seat availability for intermediate station pairs on same train.
6. Multiple supported classes.
7. General quota `GN`; Tatkal `TQ` (verified 2026-11-15: accepted, echoed, Tatkal fare, only the
   requested date returned). Premium Tatkal `PT` is
   rejected by RailKit (`400 Quota not allowed`, 2026-11-15) and is not offered. See docs/09 Q16.
8. Current status variants: CNF, AVL, RAC, WL, unavailable.
9. Prediction field presence and meaning.
10. Whether prediction is for the requested date/status and how it is refreshed.
11. Whether `canBook=true` can coexist with WL/RAC.
12. Whether availability endpoint accepts the train's originating journey date for intermediate stations after midnight.
13. API rate limits, monthly quota, burst concurrency and billing units.
14. Caching, persistence, display and commercial redistribution rights.
15. Provider behaviour when station pair is not a valid stop pair.

Do not fabricate live responses. Save sanitized examples as fixtures after successful calls.

## 10. Provider abstraction test

Create a `MockRailwayProvider` implementing the same interface. All optimizer tests must use mock/domain data and run without RailKit credentials. This is mandatory for CI and reproducible development.

## 10. Reservation quotas (added 2026-11-15)

- The adapter sends the quota code unchanged in the seat-availability path
  (`/api/v1/seats/{train}/{from}/{to}/{DD-MM-YYYY}/{class}/{quota}`) and validates the echoed
  `data.train.quota` (a TQ payload is rejected for a GN query and vice versa).
- `RailKitProvider.supported_quotas` comes from `RAILKIT_SUPPORTED_QUOTAS` (default `GN,TQ`). A query
  for any other quota raises `PROVIDER_REJECTED` **without an HTTP request**; the search service never
  gets that far, because the eligibility service marks it `PROVIDER_UNSUPPORTED` first.
- Opening times are not provided by RailKit; they are RailRoute configuration (`TATKAL_*`) applied to the train's origin date from `trainInfo`/`route[]`.
- Live evidence: `backend/tests/fixtures/railkit/live/2026-11-15/`, pinned by
  `tests/unit/providers/test_railkit_live_fixtures.py`.
