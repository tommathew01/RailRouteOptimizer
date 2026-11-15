# 02 — System Architecture and Design

## 1. Architecture principles

1. **Provider independence:** RailKit is an adapter, not the core domain.
2. **Backend authority:** All provider calls, API keys, quotas, caching and optimization run on the backend.
3. **Deterministic optimization:** Same normalized inputs must produce the same ranked output.
4. **Explicit uncertainty:** Missing or partial data is `UNKNOWN`, never assumed available.
5. **Progressive discovery:** Query only as much as the request budget permits and report coverage.
6. **Mobile-ready API:** Web and future native clients consume the same versioned REST API.

## 2. Logical architecture

```text
Web / PWA (Next.js + TypeScript)
             |
             | HTTPS / JSON
             v
       FastAPI REST API
             |
       Journey Orchestrator
        /       |        \
       v        v         v
 Train Service  Search    Availability Query Planner
       |        Cache          |
       v                       v
 RailKit Adapter <------ Availability Service
       |                       |
       v                       v
 RailKit REST API        Normalized Segment Records
                               |
                               v
                       Optimization Engine
                       /       |        \
                  Graph     Path Finder  Ranker
                       \       |        /
                               v
                         Result Assembler
                               |
                    PostgreSQL + Redis
```

## 3. Recommended deployment units

MVP can be a modular monolith:
- `frontend`: Next.js application.
- `backend`: FastAPI application.
- `postgres`: persistent relational database.
- `redis`: caching, distributed locks and rate-limit counters.

Do not start with microservices. Keep module boundaries clean so services can be split only when scaling evidence justifies it.

## 4. Backend module responsibilities

### API layer
- Validate request shape and types.
- Apply authentication/authorization when accounts are introduced.
- Apply request-level rate limits.
- Call application services.
- Return stable response schemas.

### Application/service layer
- Orchestrate train discovery, route retrieval, availability planning and optimization.
- Manage search lifecycle and partial completion.
- Apply request budget and concurrency controls.

### Provider integration layer
- Own RailKit URL construction, headers, HTTP client, retries, timeout and provider response parsing.
- Translate provider errors into internal provider exceptions.
- Never expose provider secrets or raw stack traces.

### Domain layer
- Train, station, stop, segment, availability, prediction and recommendation models.
- No FastAPI, HTTPX, SQLAlchemy or RailKit imports.

### Optimization layer
- Build a forward-only graph.
- Find paths with 1–4 edges.
- Apply eligibility and ranking rules.
- No external network access.

### Persistence layer
- Repositories for search, train-route cache and availability snapshots.
- SQLAlchemy 2.x async or sync implementation; select one consistently.
- Alembic migrations.

## 5. Frontend architecture

Recommended stack:
- Next.js App Router
- TypeScript strict mode
- React
- Tailwind CSS or another consistent design system
- TanStack Query for API state/caching
- Zod for client-side form validation (backend remains authoritative)

Suggested feature structure:

```text
frontend/web/
  app/
    page.tsx
    search/page.tsx
    results/[searchId]/page.tsx
  components/
    StationAutocomplete/
    JourneySearchForm/
    TrainResultCard/
    SegmentTimeline/
    AvailabilityBadge/
    PredictionIndicator/
    SearchCoverageNotice/
  features/
    journey-search/
    journey-results/
  lib/
    api-client.ts
    schemas.ts
  types/
```

The UI should show:
- Search form: source, destination, date, classes.
- Train list and journey route.
- Recommended segment combinations.
- A horizontal/vertical segment timeline.
- Per-segment actual status and prediction.
- Search completeness, checked-at time and provider warnings.
- Booking warning and external booking guidance.

## 6. End-to-end request flow

1. Client calls `POST /api/v1/journeys/optimize`.
2. API validates station codes, date, classes and max-segment policy.
3. Orchestrator creates a `search_id`.
4. Train service calls RailKit train-between-stations endpoint.
5. For each candidate train, fetch route details and validate source/destination ordering.
6. Query planner chooses candidate station-pair availability requests.
7. Availability service checks Redis cache and request deduplication.
8. Cache misses are sent to RailKit with bounded concurrency.
9. Adapter maps raw responses to domain availability records.
10. Persist sanitized raw payload and normalized observation.
11. Graph builder creates edges only for checked, eligible segments.
12. Path finder enumerates paths up to four edges.
13. Ranker sorts paths using deterministic rules.
14. Result assembler attaches fare/prediction/availability timestamps and coverage metadata.
15. API returns results or a search resource for polling if asynchronous execution is used.

## 7. Search execution model

For small request volumes, a synchronous request may work, but multi-train and multi-class availability fan-out can exceed normal HTTP request timeouts.

Recommended design:
- `POST /journeys/optimize` creates a search and returns `202 Accepted` with `search_id` when work is queued.
- Background worker processes provider calls.
- Client polls `GET /journeys/{search_id}`.
- For a very small initial deployment, the same service may execute a bounded search synchronously behind the same orchestration interface.
- Do not introduce Celery unless required; a lightweight worker (e.g. Celery/RQ/Arq) can be selected based on deployment constraints. Document the choice.

## 8. Provider failure isolation

A single failed segment query must not fail the entire train search. Store a segment-query outcome:
- `SUCCESS`
- `PROVIDER_TIMEOUT`
- `RATE_LIMITED`
- `AUTH_ERROR`
- `NOT_FOUND`
- `INVALID_RESPONSE`
- `UPSTREAM_ERROR`

A path can only include successful, interpretable availability edges. Failed or unqueried pairs are not treated as unavailable; they are unknown and reduce search completeness.

## 9. Security architecture

- RailKit API key stored in backend secret environment or secret manager.
- Never send key to frontend.
- Redact `x-api-key`, authorization headers and secrets from logs.
- HTTPS in production.
- CORS allowlist.
- Input validation and maximum request limits.
- Provider request budget enforced on server, never trusted from client.
- Avoid storing passenger data; MVP does not request it.
- Protect admin/metrics endpoints.
- Add authentication and subscription controls before public paid launch.
- Use dependency scanning, pinned dependencies and container image scanning.

## 10. Deployment topology

Development:
- Docker Compose: frontend, backend, PostgreSQL, Redis.
- `.env` files ignored by Git.
- Mock provider enabled for automated tests.

Production:
- Frontend hosted on a managed Next.js platform or container.
- FastAPI container behind HTTPS reverse proxy/load balancer.
- Managed PostgreSQL with backups.
- Managed Redis.
- Centralized logs and metrics.
- Secret manager.
- Separate staging and production RailKit credentials if supported.

## 11. Architecture decisions (ADRs)

- ADR-001: Modular monolith for MVP.
- ADR-002: Next.js web/PWA first; native mobile later.
- ADR-003: RailKit accessed via REST from FastAPI.
- ADR-004: Provider adapter isolates external API.
- ADR-005: DAG represents one train's forward station route.
- ADR-006: Maximum four segments.
- ADR-007: General quota only in MVP. **Superseded 2026-11-15** by docs/08 D-20…D-25 (GN/TQ,
  separate search spaces, eligibility service `app/services/quota_eligibility.py` over the pure
  `app/domain/quota_eligibility.py`).
- ADR-008: Provider prediction is optional secondary ranking input, not truth.
- ADR-009: No passenger count; segment check is one-ticket availability.
- ADR-010: Search completeness and API budget are first-class response fields.
