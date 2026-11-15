# 06 — Data Model, Caching, Security, Testing and Operations

## 1. PostgreSQL schema (logical)

### stations
- `id` UUID primary key
- `code` varchar unique not null
- `name` varchar not null
- `city` nullable
- `metadata_json` JSONB nullable
- `created_at`, `updated_at`

### trains
- `train_number` varchar primary key
- `train_name`
- `metadata_json` JSONB
- `updated_at`

### train_routes
- `id` UUID
- `train_number` FK
- `route_version` or provider update marker
- `journey_date` nullable if route differs by operating day
- `fetched_at`
- `route_verified`
- unique/index by train and applicable date/version

### train_stops
- `id` UUID
- `route_id` FK
- `sequence_index` integer
- `station_code` FK
- `arrival_time` nullable
- `departure_time` nullable
- `day_offset` integer default 0
- `is_stoppage` nullable
- unique `(route_id, sequence_index)`

### journey_searches
- `id` UUID
- `source_station_code`
- `destination_station_code`
- `journey_date` date
- `classes` JSONB
- `quota` default `GN`
- `filters` JSONB
- `status`
- `search_completeness`
- `incomplete_reason`
- `request_budget`
- `requests_made`
- `created_at`, `completed_at`

### availability_observations
- `id` UUID
- `train_number`
- `journey_date`
- `source_station_code`
- `destination_station_code`
- `travel_class`
- `quota`
- `status`
- `availability_text`
- `raw_status`
- `waitlist_type` nullable
- `waitlist_number` nullable
- `available_count` nullable
- `can_book` nullable
- `prediction_text` nullable
- `prediction_percentage` nullable
- `fare_amount` nullable
- `currency` nullable
- `provider` (`RAILKIT`)
- `provider_checked_at`
- `observed_at`
- `raw_payload` JSONB (sanitized)
- indexes for query identity and timestamps

Do not overwrite observations; retain snapshots according to data retention policy.

### segment_query_runs
- `id` UUID
- `search_id` FK
- segment identity fields
- state/outcome
- provider latency
- cache_hit
- error_code nullable
- observation_id nullable
- created_at

### recommendations
- `id` UUID
- `search_id` FK
- `rank`
- `train_number`
- `travel_class`
- `segment_count`
- `ranking_metadata` JSONB
- `total_fare` nullable
- `fare_complete`
- created_at

### recommendation_segments
- `id` UUID
- `recommendation_id` FK
- `sequence_index`
- `availability_observation_id` FK
- from/to station codes
- unique `(recommendation_id, sequence_index)`

### provider_usage
- `id` UUID
- provider
- endpoint
- request_count
- status_code
- latency_ms
- search_id nullable
- created_at

## 2. Important indexes

- `stations(code)` unique.
- `train_stops(route_id, sequence_index)` unique.
- `availability_observations(train_number, journey_date, source_station_code, destination_station_code, travel_class, quota, observed_at desc)`.
- `journey_searches(created_at desc)`.
- `segment_query_runs(search_id, state)`.
- `recommendations(search_id, rank)`.

## 3. Cache policy

Redis keys:
- `station-search:{normalized_query}`
- `train-search:{from}:{to}:{date}`
- `train-route:{train_number}:{route_version}`
- `availability:{train}:{date}:{from}:{to}:{class}:GN`
- `search-lock:{availability_key}`

Availability TTL must be configurable and validated against RailKit's documented terms and freshness. Start with a conservative short TTL in development; do not assume caching is permitted at any duration without checking the provider agreement.

Use cache single-flight to avoid duplicate concurrent requests. Cache only successful, schema-valid responses. Do not cache auth failures or malformed responses as valid availability.

## 4. Observability

Structured logs should include:
- `request_id`
- `search_id`
- provider name
- endpoint name (not secret URL parameters if sensitive)
- train/date/segment/class
- cache hit/miss
- latency
- HTTP status/error category
- request budget counters

Never log API keys, authorization headers, passenger identity or payment information.

Metrics:
- provider requests by endpoint/status
- provider latency p50/p95
- provider 429 and 5xx rate
- cache hit ratio
- search duration
- paths found per search
- partial-search percentage
- budget exhaustion rate
- prediction coverage
- malformed provider response count

## 5. Testing strategy

### Unit tests
- status normalization
- prediction parsing
- route ordering
- date/day-offset handling
- graph construction
- path enumeration
- ranking determinism
- fare aggregation completeness
- request budget planner
- cache key generation

### Contract tests
- RailKit train search payload fixture
- train info route fixture
- seat availability fixtures for CNF/AVL/RAC/WL/unavailable
- prediction missing, string, numeric, malformed and out-of-range
- provider error envelope

Contract tests should run against sanitized fixtures by default. Live tests must be opt-in and require an environment variable.

### Integration tests
- FastAPI + test database + mocked RailKit transport.
- Redis cache hit and request deduplication.
- Provider timeout and partial failure.
- Search result persistence and retrieval.

### End-to-end tests
- Search TIR → TVC.
- One train with a direct segment.
- One train with 2–4 segment combinations.
- Search across two selected classes.
- Search where WL disabled.
- Partial budget result banner.
- Mobile viewport and accessibility.

## 6. Security and privacy

- `.env` never committed.
- `.env.example` contains placeholders only.
- Use Pydantic Settings.
- Secrets manager in production.
- Rotate provider keys if exposed.
- CORS allowlist.
- HTTPS.
- Dependency pinning and security updates.
- Request validation and body size limits.
- Do not collect passenger names, age, gender, PNR, credentials or payment data for MVP.
- Define data retention and deletion policy for search history and raw payloads.
- Review RailKit's commercial and redistribution terms before public launch.

## 7. Operational runbook

### RailKit 401/403
Check key presence, validity, account state and server secret configuration. Do not retry repeatedly.

### RailKit 429
Stop or throttle requests, honor any retry guidance, use bounded backoff and surface partial search. Do not spin-retry.

### RailKit 5xx / timeout
Retry only idempotent GET requests with bounded exponential backoff and jitter. Preserve successful segment observations.

### Unexpected payload
Mark that segment `UNKNOWN` / `INVALID_RESPONSE`, record sanitized fixture and alert. Do not guess status.

### Redis unavailable
Use a controlled fallback only if provider request limits remain safe; otherwise fail closed or reduce query scope. Never bypass provider budget controls.

### PostgreSQL unavailable
Do not report results as durably saved. Return a clear service error or use an explicitly designed transient mode.

## 8. Commercial launch gates

Before public launch:
- Confirm RailKit permits commercial use and redistribution of derived availability/prediction.
- Confirm rate limits, billing units, burst concurrency and overage behaviour.
- Confirm caching/storage restrictions and retention.
- Confirm whether API data can be shown to end users.
- Confirm endpoint uptime/support expectations.
- Add user authentication, per-user quotas and abuse protection.
- Add privacy policy, terms, disclaimers and support contact.
- Conduct security review and load test.
- Monitor provider cost per completed search.
