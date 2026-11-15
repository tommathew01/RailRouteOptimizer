# 08 — Implementation Plan, Decisions and Open Questions

Status: living document. It records how the documentation pack (`01`–`07`) is being implemented,
which decisions were taken where the pack was silent, and which provider-contract questions are
still open. Binding product decisions are unchanged (see `docs/README.md`).

## 1. Milestones

| # | Milestone | Exit criteria |
|---|---|---|
| 1 | Repository and foundation | Monorepo layout, Compose (Postgres, Redis, app profile), typed settings, structured logging, FastAPI health/readiness, Next.js shell, lint/type/test tooling green |
| 2 | Provider contract | Provider protocol, mock provider, RailKit HTTP client + mapper + provider, documentation-derived fixtures, status/prediction normalization, opt-in live contract tests |
| 3 | Domain and optimizer | Route validation + day offsets + segment date policy, adaptive query planner, graph builder, bounded path finder (1–4 edges), deterministic ranker, exhaustive unit tests |
| 4 | Persistence and caching | ORM models + Alembic migration, persistence gateway (Postgres + in-memory), Redis/in-memory store, cache + single-flight, provider quota guard, usage recording |
| 5 | API orchestration | Station/train/availability services, journey search lifecycle (202 + polling, sync mode), progress + partial results, error envelope, rate limiting |
| 6 | Frontend | Search form (autocomplete, swap, date, classes, fixed GN), train list + route timeline, optimization progress, recommendation cards, prediction attribution, coverage/stale/demo notices, booking guidance |
| 7 | Hardening | Security headers, metrics endpoint, accessibility pass, Dockerfiles, CI workflow, runbook and deployment docs |

## 2. Repository layout

```text
Railway_Route_Optimizer/
  compose.yaml                 # Postgres + Redis by default; backend/frontend under the "app" profile
  .env.example                 # every variable, placeholders only
  infrastructure/postgres/initdb/   # creates the least-privilege runtime role
  docs/                        # product + engineering docs (this file is 08)
  backend/
    pyproject.toml, uv.lock, alembic.ini, Dockerfile
    migrations/                # Alembic (async env)
    app/
      main.py                  # create_app() factory
      container.py             # composition root (settings -> services)
      core/                    # config, logging, request context, errors, clock, metrics
      domain/                  # pure models + IR status/prediction parsing + route rules (stdlib only)
      optimization/            # planner, graph, path finder, ranker (stdlib + domain only)
      providers/               # RailwayProvider protocol, provider errors, mock provider, factory
      integrations/railkit/    # HTTP client, lenient DTOs, mapper, provider (only RailKit-aware code)
      cache/                   # key-value store (Redis / memory), single-flight
      services/                # stations, trains, availability, budget guard, journey orchestration
      repositories/            # persistence gateway protocol + SQLAlchemy + in-memory implementations
      database/                # SQLAlchemy base, ORM models, engine/session factory
      schemas/                 # public API request/response models (Pydantic)
      api/                     # middleware, error handlers, rate limit, v1 routers
    tests/                     # unit/, integration/, live/ (opt-in), fixtures/railkit/
  frontend/web/                # Next.js App Router + TypeScript + Tailwind + TanStack Query + Zod
```

Deviation from the master prompt: Compose stays at the repository root as `compose.yaml` (the
existing file) so `docker compose up` picks up the root `.env` without extra flags.
`infrastructure/` holds the database init scripts and deployment notes.

## 3. Decisions taken where the pack was silent

| ID | Decision | Rationale |
|---|---|---|
| D-01 | `journey_date` at our API is the **date the passenger departs the requested source station** (IST). Internally every segment is keyed by the **train start (origin) date**, derived from the route's day offsets, so all segments of one train run share one canonical date. | Users and RailKit train search speak in boarding dates; doc 03 requires the originating date as the canonical identity. |
| D-02 | The date sent to RailKit availability is controlled by `AVAILABILITY_DATE_POLICY`: `SEGMENT_BOARDING_DATE` (default — date the train departs the segment's from-station) or `TRAIN_START_DATE`. Segments whose boarding date differs from the source date are flagged and a warning is returned until the contract is verified live. | Doc 03 forbids silently changing the date; this keeps the choice explicit, configurable and visible. Default follows the IRCTC convention that RailKit's docs examples are consistent with. |
| D-03 | Ranking key 4 ("higher provider prediction") is the **minimum RailKit percentage across RAC/WL segments**. It is neutral for all-confirmed paths and sorts last when any RAC/WL segment lacks a percentage. Freshness is bucketed per minute. | Without this, a two-ticket all-available path with a "100%" label could outrank a direct available ticket. Minimum is a non-probabilistic weakest-link descriptor; nothing is multiplied. |
| D-04 | The query planner is **adaptive and wave-based**: depth 1 (direct) for every train×class first, then 2-, 3- and 4-segment candidates in round-robin across train×class combinations; a candidate's next edge is queried only after its previous edges are usable; candidates through ineligible edges are pruned; a combination stops once it has an all-confirmed path (deeper paths cannot outrank it). | RailKit plans allow 50–10,000 requests/month; exhaustive N(N−1)/2 querying is not viable. |
| D-05 | Optional `train_numbers` on the optimize request, and a two-step UI (find trains → choose trains → optimize). | Primary user "has a preferred train"; avoids spending quota on trains the user does not want. |
| D-06 | Background execution uses an **in-process asyncio executor** with state persisted in PostgreSQL; `SEARCH_EXECUTION_MODE=sync` runs inline (tests/dev). Searches left RUNNING by a crashed process are marked FAILED at startup. A Redis-backed worker (Arq) can replace the executor behind the same interface. | Doc 02 §7 asks for the lightest worker that works; no Celery. |
| D-07 | Global provider **quota guard** in Redis: fixed 10-minute window + calendar-month (IST) counters, checked before every HTTP attempt including retries; 429 sets a shared back-off. If Redis is unavailable in `railkit` mode, provider calls **fail closed**. | Doc 06 §7: never bypass provider budget controls. |
| D-08 | Direct REST with the `x-api-key` header only. The SDK's signed `x-irctc-sdk-*` headers are not replicated. | Using an SDK-embedded signing secret would circumvent the provider's access model. |
| D-09 | Persistence gateway with a SQLAlchemy (PostgreSQL) implementation and an in-memory implementation for tests and zero-infrastructure demo mode. The final/partial API result is stored as a JSONB snapshot on `journey_searches`; normalized recommendation tables are written for audit/analytics. | Fast retrieval, durable audit, infrastructure-free unit/API tests. |
| D-10 | Train-specific class filtering uses `trainInfo.classes` when supplied; a selected class the train does not list is reported as `CLASS_NOT_OFFERED` without spending availability calls. Globally unsupported classes are a 422. | Doc 03 §4 requires checking train-specific support where available. |
| D-11 | Additional segment-query outcome `PROVIDER_REJECTED` for provider 400 responses (e.g. invalid stop pair). | Neither "not available" nor an upstream fault; doc 02 §8's list has no slot for it. |
| D-12 | `provider_checked_at` is `null` because RailKit does not return a check timestamp; `observed_at` (when we received the response) is shown as "checked at". | Never fabricate provider fields. |
| D-13 | Station search: minimum 3 characters before calling the provider, results cached, frontend debounced. | Every keystroke would otherwise spend provider quota. |

## 4. Conflicts found in the documentation pack

1. `README.md` lists `agent/AI_CODING_AGENT_MASTER_PROMPT.md` and `agent/IMPLEMENTATION_CHECKLIST.md`; neither exists in the repository (the master prompt was supplied in chat).
2. Doc 04 §5 ranking order (prediction before segment count) contradicts the product goal of minimising tickets for all-confirmed paths when predictions are present on confirmed segments — resolved by D-03.
3. Doc 03 §2 (originating date is canonical) vs doc 05 (`journey_date` undefined) — resolved by D-01/D-02.
4. Doc 06 `availability_observations.journey_date` cannot represent both the canonical train start date and the provider query date — both columns are stored.
5. RailKit's own documentation disagrees on the classes accepted by seat availability (docs page: 15 codes; SDK README: 8). Default `SUPPORTED_CLASSES` is the intersection: `1A,2A,3A,3E,SL,CC,EC,2S`.

## 5. Open provider-contract questions

See `09_RAILKIT_CONTRACT_VERIFICATION.md` for the evidence collected and the live checklist.
None of these block development: the mock provider and documentation-derived fixtures cover them,
and each has a defensive default.

## 6. Decisions added during implementation

| ID | Decision | Rationale |
|---|---|---|
| D-14 | Partial results are republished at most once per second (always after the first wave, and at completion). | Rebuilding graphs, ranking and the snapshot after every wave cost ~33 ms of event-loop time per wave; a 439-request search dropped from 4.4 s to 0.8 s of CPU with identical results. |
| D-15 | Only *stale* QUEUED/RUNNING searches (no progress for `SEARCH_DEADLINE_SECONDS` + 5 min) are marked `FAILED / INTERRUPTED`, at startup and lazily when polled; partial results are kept. | Failing every unfinished search at startup would kill searches running on other healthy replicas during rolling deploys. |
| D-16 | Retention via `python -m app.cli purge`: raw payloads 14 days, searches/observations 90 days, provider usage 400 days (all configurable). | Doc 06 §6 requires a retention policy for search history and raw payloads; runs with the DML-only runtime role. |
| D-17 | The Compose backend trusts one proxy hop (`COMPOSE_TRUSTED_PROXY_HOPS=1`); the application default stays `0`. | Behind the Next.js proxy every user would otherwise share one rate-limit bucket. Spoofing caveat and production setup: runbook §4. |
| D-19 | Live contract run 2026-11-14 verified D-02's default (`SEGMENT_BOARDING_DATE`); the after-midnight warning now appears only for the contradicting `TRAIN_START_DATE` policy. Trains RailKit matched to nearby stations get a one-click search for their own station pair. | Evidence in docs/09 §5. |
| D-18 | The frontend's `npm start` runs the standalone server the same way the Docker image does (`scripts/start-standalone.mjs`); e2e tests use it. | `next start` is unsupported with `output: "standalone"`; tests should exercise what ships. |

## 7. Status

All seven milestones are implemented and the core RailKit contract is verified live (docs/09 §5).
Still open: Q10, Q12 (invalid stop pair) and Q13 in docs/09, plus the non-contract launch gates
(runbook §9).
