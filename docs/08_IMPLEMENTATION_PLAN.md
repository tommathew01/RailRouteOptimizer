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
| D-04 | *(Scheduling superseded by D-27.)* The query planner is **adaptive and wave-based**: depth 1 (direct) for every train×class first, then 2-, 3- and 4-segment candidates in round-robin across train×class combinations; a candidate's next edge is queried only after its previous edges are usable; candidates through ineligible edges are pruned; a combination stops once it has an all-confirmed path (deeper paths cannot outrank it). | RailKit plans allow 50–10,000 requests/month; exhaustive N(N−1)/2 querying is not viable. |
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

## 6a. Tatkal (2026-11-15)

Replaces binding decision "General quota only" (docs/README, ADR-007) at the product owner's request.

| # | Decision | Rationale |
|---|---|---|
| D-20 | Quotas `GN` (default) and `TQ`; the optimize request takes `quotas` (1–2). Every **train × class × quota** is a separate planner combination, graph and path set, created quota-major (GN first). The legacy single `quota` field stays ignored. | Never mix quotas; a General-only search is planned, budgeted and ranked exactly as before (verified: identical provider calls and results with a closed TQ added). |
| D-21 | Eligibility is a pure domain function (`app/domain/quota_eligibility.py`) behind `QuotaEligibilityService` (injectable clock). Window = train **origin date** − `days_before` (1) at 10:00 IST (AC) / 11:00 IST (non-AC), configurable. States: `NOT_APPLICABLE`, `NOT_YET_OPEN`, `OPENS_TODAY`, `OPEN`, `OPENING_PASSED`, `JOURNEY_DATE_PASSED`, `CLASS_CATEGORY_UNKNOWN`, `UNDETERMINED`, `PROVIDER_UNSUPPORTED`; only the first, `OPEN` and `OPENING_PASSED` are queried. One `now` per search. | The boarding date is later than the origin date for stops reached after midnight; using it would open the window a day late. `OPENING_PASSED` is queried because Tatkal stays bookable until charting — the provider's answer decides. |
| D-22 | One class-category map (AC: 1A 2A 3A 3E CC EC EA VA; non-AC: SL 2S FC VS). `VC`, `CH`, `HS` are unclassified and never queried for TQ. No class-level Tatkal exclusions (e.g. 1A) are encoded; the provider's answer decides. | Never guess an opening time; avoid encoding unverified railway rules. |
| D-23 | Not-queried combinations spend no budget, are reported per class (`NOT_YET_OPEN` / `QUOTA_NOT_SUPPORTED` / `NOT_QUERIED` + `eligibility`) and per quota (`quotas[]`), and make the search `PARTIAL_QUOTA_NOT_QUERIED` / `QUOTA_NOT_QUERIED` (budget, timeout and provider reasons take precedence). No automatic re-query. | "Not checked" must never read as "unavailable" or "no path exists". |
| D-24 | Provider support is part of the provider interface (`supported_quotas`). RailKit = `RAILKIT_SUPPORTED_QUOTAS` (default `GN,TQ`; TQ verified live). If **no** selected quota is supported → `422 QUOTA_NOT_SUPPORTED` before any provider call; otherwise unsupported quotas are reported and nothing is substituted. | Spec: verify the provider, report clearly, never fall back silently. |
| D-26 | **Premium Tatkal (`PT`) removed** at the product owner's request ("not required/available"). The live probe had already shown RailKit rejecting it (`400 Quota not allowed`, docs/09 Q16). `Quota`, settings (`PREMIUM_TATKAL_*`), mock behaviour, schemas, UI and tests no longer mention it; `PT` is now an unknown code (HTTP 400, or an invalid `quotas` URL parameter). `RAILKIT_SUPPORTED_QUOTAS` is kept so Tatkal can be switched off without a code change. | The option was not usable; keeping dead configuration and a permanently "not supported" chip only confuses users. Nothing persisted a `PT` value (the quota feature had not been deployed). |
| D-25 | `journey_searches.quotas` JSONB (migration `3b7d2c9a41e6`, default `["GN"]`); the legacy `quota` column keeps the first selected quota. All response additions have defaults, so stored snapshots from before the change still load. The availability check endpoint now honours `quota` (`null` → GN). | Additive, backward-compatible schema and API. |

## 6b. Fair budget allocation (2026-11-15)

Follows the architecture review of API consumption. Scope: GN and TQ only (Premium Tatkal stays
removed, D-26).

| # | Decision | Rationale |
|---|---|---|
| D-27 | **Fair, progressive scheduling** in `QueryPlanner.next_wave` (replaces the wave rotation of D-04). Every query slot goes to the active combination with the smallest key *(depth, queries at that depth, result quality, round-robin distance)*: all direct tickets before any 2-ticket exploration, every 2-ticket level before any 3-ticket level, equal shares within a level, combinations without any complete path before waitlist-only before RAC-only ones, and a persistent cursor that moves past the last combination served. Solved/exhausted combinations drop out, so their share flows to the others. The search orders combinations for the round-robin with quotas interleaved (GN, TQ, GN, TQ…); combination ids stay quota-major. | **Bug fixed:** the old planner moved its starting point by one combination per wave and filled each wave from there, so only about ⌊B/W⌋ + W − 1 combinations were ever queried (10 of 40 at B=30/W=4, 19 of 40 at B=100/W=8); later trains and most Tatkal combinations never got a direct check, contradicting D-04. Ranking is unchanged. Dominance pruning for RAC/WL searches was **not** added (it would change which results can appear). |
| D-28 | **Retries are paid from the search budget.** `SEARCH_MAX_AVAILABILITY_REQUESTS` now caps provider *attempts*. A logical check reserves its first attempt; the RailKit client reports every attempt and asks the per-call gate (`app.providers.base.call_gate`) before each retry; a refused retry ends the call with its real error (segment "not checked", never "unavailable"). Calls are settled against attempts made: a guard refusal costs nothing, cache hits and single-flight followers never reserve. Coverage reports `availability_requests_made` (attempts), `availability_checks_made` (logical), `availability_retries`, `availability_retries_refused`. The global guard still checks every attempt. | Retries could previously double a search's real consumption (B logical calls + up to B × `RAILKIT_MAX_RETRIES` retries). Retries are kept, not disabled. Adapters that do not report attempts (mock) count one per call. |
| D-29 | **Selection limits are server settings**, published in `/meta`: `SEARCH_MAX_TRAINS` (5), `SEARCH_MAX_CLASSES` (3); the train list pre-selects no train (D-32). Above a limit the API answers `400 TOO_MANY_TRAINS` / `TOO_MANY_CLASSES` — it never truncates; the UI disables further choices and explains old over-limit links. `POST /journeys/preview` returns the exact combinations a search would query now (same preparation code, Tatkal eligibility included), the budget and the depth trade-off, without any availability request. | 5 trains × 3 classes × 2 quotas = 30 = the default budget, so every direct ticket stays checkable. Multiple classes are kept (each class needs its own provider call; routes, eligibility and caches are shared). The preview loads only the selected trains' routes (cached 24 h, needed by the search anyway). |
| D-30 | **Docker/local configuration parity.** The Compose backend forwards every application setting by name (`KEY:` without a value), so Compose resolves it from the root `.env` or leaves it unset and `config.py`'s default applies — defaults are never repeated in `compose.yaml`. Only `DATABASE_URL`, `REDIS_URL` and `TRUSTED_PROXY_HOPS` are container-specific; admin database credentials are not passed to the runtime. `tests/unit/core/test_compose_parity.py` enforces this. | Before, Docker silently ignored e.g. `RAILKIT_MAX_CONCURRENCY`, `SEARCH_MAX_TRAINS`, cache TTLs and the `TATKAL_*` settings. Verified on 2026-11-15 with a real container: 55 effective settings identical to the host run. |

## 6c. Maintenance window, result filters, train selection (2026-11-16)

| # | Decision | Rationale |
|---|---|---|
| D-31 | **IRCTC maintenance window 23:45–00:20 IST.** `MaintenanceWindow` (pure domain, IST wall clock, may cross midnight, end exclusive) + settings `RAILWAY_MAINTENANCE_ENABLED/START/END`. One route dependency (`railway_services_open`, before the rate limits) refuses `POST /trains/search`, `GET /trains/{n}/route`, `POST /availability/check`, `POST /journeys/optimize` and `/journeys/preview` with `503 RAILWAY_MAINTENANCE` (+ `Retry-After`, `details.available_at`). A search already running stops sending requests when the window begins (`incomplete_reason = RAILWAY_MAINTENANCE_WINDOW`). Stored results (`GET /journeys/{id}`), station search and `/meta` stay available. `/meta.railway_maintenance` lets the UI explain the window, disable search actions and re-enable them by itself (10 s re-check). | Mirrors IRCTC. Evaluating an aware instant in `Asia/Kolkata` makes the server's and the device's timezone irrelevant (IST is fixed UTC+05:30, so the browser uses plain offset arithmetic on `Date.now()`). Station search is not train or availability data, so it stays open. |
| D-32 | **No train is pre-selected** on the train list; proceeding with none shows "Select at least one train…" and sends nothing. `SEARCH_DEFAULT_TRAINS` / `limits.default_trains_selected` were removed. An explicit empty `train_numbers` is now a 400 (omitting it still means "all trains"). | Product decision; an empty list used to mean "all trains" silently. |
| D-33 | **Result filters** (class, quota, train chips + train number/name search) run in the browser on the recommendations already loaded: AND across categories, OR within one; no request, the response object is never modified, ranks are kept. Groups with a single value are hidden. | Lets users narrow results without spending provider requests. |

## 6d. Redundant split tickets (2026-11-17)

| # | Decision | Rationale |
|---|---|---|
| D-34 | **Dominance pruning.** A combination is *dominated* when two or more of its consecutive segments, from stop a to stop b, are covered by the single segment a → b that is CONFIRMED/AVAILABLE for the same train run, class and quota (`app/optimization/dominance.py`). The planner prunes such candidates before requesting their remaining segments (`QueryPlanner._evaluate/_generate`), and `find_paths` never returns them. RAC, waitlist and any prediction (even 100 %) never dominate. The planner's "solved" check now looks at every complete path over the known usable segments, not only the current depth's candidates. | Screenshots of 22504 / 22634 (2026-11-17) showed DBRG→MXN→NCB→CAPE next to DBRG→NCB→CAPE with DBRG→NCB available. The merged path uses only segments the split needs plus the available one, is no worse on status tier and prediction floor, and has fewer tickets, so it always ranks strictly higher; only total fare could favour a split, and ticket count already outranks fare. Because each depth finishes before the next, every segment that can dominate a candidate is known before the candidate is reached. Measured: same useful results in every scenario, 19–88 % fewer requests where availability allows (0 % when nothing is available); demo API case 105 → 27 requests. |

## 6e. Stop search, top 10 (2026-11-17)

| # | Decision | Rationale |
|---|---|---|
| D-35 | **Stop search.** `POST /journeys/{id}/stop` (idempotent; 202 when a running search was asked to stop, 200 when it had finished). The stop is stored as a shared flag (`search-stop:{id}` in Redis, TTL = deadline + grace) so whichever replica runs the search sees it, and applied immediately to a search running in the receiving process. A stopped search: sends no new wave (checked before each wave and before train discovery); its `SearchBudget` refuses new checks and retries; a RailKit request that has not been sent yet — e.g. waiting for a connection slot — is withdrawn (`ensure_may_start`, checked before the quota guard and again just before sending). Requests already sent finish and are kept. Result: `COMPLETED` + `PARTIAL_STOPPED` / `STOPPED_BY_USER` (or `NO_PATH_FOUND_PARTIAL`), ranked from what was checked. Withdrawn segments are "not checked", never "unavailable". A refusal inside the in-process single-flight now carries its budget, so another search sharing that request asks for itself instead of inheriting it. | Cancelling the browser request would not stop the backend loop or the provider calls; the stop must reach the planner loop and the provider client. |
| D-36 | **Top 10.** `MAX_RECOMMENDATIONS` default 20 → 10. Ranking is unchanged: every path found is ranked and the first N kept, so a completed search shows the best 10 of everything checked and a partial one the best 10 of what was checked (labelled as such in the UI). An early stop based on the 10th result (no deeper path can outrank an all-confirmed 10th result) was prototyped and proved result-identical over 150 searches, but saved requests in only 1 of them (0.4 %): the existing per-combination stop already captures it, so it was not kept. | Results beyond 10 added little value. |

## 6f. Production hosting (2026-11-18)

| # | Decision | Rationale |
|---|---|---|
| D-37 | **Render, Singapore, defined in `render.yaml`**: public Next.js web service, private FastAPI service (pre-deploy `alembic upgrade head`, `maxShutdownDelaySeconds: 120`), managed PostgreSQL 18, Key Value with `noeviction`, daily retention cron; deploys only after GitHub CI passes. Deployment fixes: the proxy accepts a scheme-less `host:port` backend address; `SEARCH_SHUTDOWN_GRACE_SECONDS` lets running searches finish on SIGTERM (production 95 s, default 0); the proxy forwards `Authorization` only to the token-protected operator endpoints; `GET /api/v1/ops/client-address` to calibrate `TRUSTED_PROXY_HOPS`; `managed-app-role.sql` for a DML-only role on managed PostgreSQL; CI now runs on `master`. Guide: docs/11. | Maps one-to-one onto the existing architecture (no redesign), always-on instances for in-process searches, managed data stores, deploy gating and rollbacks, ≈ $30/month. Verified locally with production images and two replicas (docs/11 §10); the Render deployment itself is not yet verified. |

## 7. Status

All seven milestones are implemented and the core RailKit contract is verified live (docs/09 §5).
Tatkal support (§6a) is implemented; Premium Tatkal was removed (D-26). Fair budget allocation,
retry accounting, selection limits and Docker parity (§6b) are implemented.
Still open: Q10, Q12 (invalid stop pair) and Q13 in docs/09, plus the non-contract launch gates
(runbook §9).
