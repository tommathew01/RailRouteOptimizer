# RailRoute Optimizer

Railway availability discovery and **same-train segment optimization** for Indian Railways.

When a direct reservation is waitlisted or unavailable, RailRoute checks shorter
station-to-station reservations on the **same train, date, class and quota** and finds combinations
of **1–4 separate tickets** that cover the whole journey, e.g.
`TIR → SRR` + `SRR → TCR` + `TCR → TVC`.

Quotas: **General (GN)** by default; **Tatkal (TQ)** can be added. Each
quota is searched separately and never mixed. Tatkal quotas are only checked once their booking
window is open (1 day before the train leaves its **origin** station, 10:00 IST for AC / 11:00 IST
for non-AC classes); before that RailRoute shows "not checked — opens at …", never "unavailable".

> RailRoute does not book tickets. Each segment is a separate reservation and may produce a
> separate PNR. It is independent and not affiliated with Indian Railways or IRCTC.

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router, Cache Components) · TypeScript · Tailwind CSS 4 · TanStack Query · Zod |
| Backend | Python 3.12 · FastAPI · Pydantic v2 · HTTPX · SQLAlchemy 2 (async) · Alembic |
| Data | PostgreSQL 18 · Redis 8 |
| Provider | RailKit REST API (backend only) · deterministic mock provider for development/CI |

Product and engineering documentation lives in [`docs/`](docs/README.md). Binding product
decisions: [`docs/README.md`](docs/README.md#final-decisions-binding). Implementation decisions
and open provider questions: [`docs/08`](docs/08_IMPLEMENTATION_PLAN.md),
[`docs/09`](docs/09_RAILKIT_CONTRACT_VERIFICATION.md).

## Quick start (demo mode — no RailKit key needed)

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/) ≥ 0.13, Node.js ≥ 24.

```bash
cp .env.example .env                 # then edit passwords; never commit .env
make setup                           # uv sync + npm ci
make infra-up                        # PostgreSQL + Redis containers
make migrate                         # create the schema (runs as the admin role)
make backend                         # API on http://localhost:8000  (docs: /api/docs)
make frontend                        # Web on http://localhost:3000
```

Everything in one command instead: `docker compose --profile app up -d --build`. Both ways read
the same root `.env`: Compose forwards every application setting to the backend container, so the
two run modes behave the same (docs/08 D-30). Re-run with `--build` after code changes.

The default `RAILWAY_PROVIDER=mock` serves **simulated** trains and availability. The UI shows a
"Demo mode" banner and the API returns `data_mode: "DEMO"` — mock data is never presented as live.

**Ports already in use?** If PostgreSQL or Redis already run natively on your machine, set
`POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` in `.env` (e.g. `55432` / `56379`) and use the same ports in
`DATABASE_URL` / `REDIS_URL`.

## Using live RailKit data

1. Get an API key from the RailKit dashboard and put it in `.env` as `RAILKIT_API_KEY=…`.
2. Set `RAILWAY_PROVIDER=railkit`.
3. Set `PROVIDER_MONTHLY_REQUEST_LIMIT` / `PROVIDER_WINDOW_REQUEST_LIMIT` to **your plan**
   (defaults are the Free tier: 50 requests/month, 100 per 10 minutes).
4. Run the live contract checks once: `make test-live` (spends a handful of real requests) and
   record the answers in `docs/09_RAILKIT_CONTRACT_VERIFICATION.md`.

The key is read only by the backend, is never sent to the browser, and is redacted from logs.

## Commands

| Command | What it does |
|---|---|
| `make check` | Lint + type-check + unit/API tests for backend and frontend (what CI runs, minus infrastructure) |
| `make test` | Backend `pytest` + frontend `vitest` |
| `make test-integration` | PostgreSQL/Redis integration tests (set `TEST_DATABASE_URL`, `TEST_REDIS_URL`) |
| `make test-e2e` | Playwright end-to-end tests (desktop + mobile, axe accessibility audit); starts its own API (mock provider) and web server |
| `make test-live` | Opt-in live RailKit contract tests (`RUN_LIVE_RAILKIT_TESTS=true`) |
| `make purge ARGS="--dry-run"` | Data-retention policy (raw payloads 14 d, searches 90 d, usage 400 d) |
| `make format` | `ruff format` + autofix |
| `make migrate` | `alembic upgrade head` |

Backend only: `cd backend && uv run pytest`, `uv run ruff check .`, `uv run mypy`.

**End-to-end tests** need Chromium: `cd frontend/web && npx playwright install --with-deps chromium`.
Without root, `npx playwright install chromium` and then provide the three missing system libraries
from user space (Ubuntu):

```bash
mkdir -p ~/.cache/railroute/chromium-libs && cd ~/.cache/railroute/chromium-libs
apt-get download libnspr4 libnss3 libasound2t64 && for f in *.deb; do dpkg -x "$f" root; done
export LD_LIBRARY_PATH=$HOME/.cache/railroute/chromium-libs/root/usr/lib/x86_64-linux-gnu
```

To run them against an already running stack (e.g. Compose): `E2E_WEB_PORT=3000 E2E_API_PORT=8000 npx playwright test`.
Frontend only: `cd frontend/web && npm run lint && npm run typecheck && npm test && npm run build`.

## Configuration

Every variable is documented in [`.env.example`](.env.example) and validated at startup by
[`backend/app/core/config.py`](backend/app/core/config.py). Highlights:

| Variable | Default | Notes |
|---|---|---|
| `RAILWAY_PROVIDER` | `mock` | `railkit` requires `RAILKIT_API_KEY`; production refuses `mock` |
| `SEARCH_MAX_AVAILABILITY_REQUESTS` | `30` | provider availability attempts per search, retries included (server-enforced) |
| `SEARCH_MAX_TRAINS` | `5` | trains selectable per search (none is pre-selected) |
| `SEARCH_MAX_CLASSES` | `3` | classes per search (5 × 3 × GN+TQ = 30 = the default budget) |
| `PROVIDER_MONTHLY_REQUEST_LIMIT` | `50` | global guard; set to your RailKit plan |
| `AVAILABILITY_DATE_POLICY` | `SEGMENT_BOARDING_DATE` | date sent for segments boarding after midnight (docs/08 D-02) |
| `AVAILABILITY_CACHE_TTL_SECONDS` | `120` | pending RailKit caching terms |
| `RAILWAY_MAINTENANCE_*` | on, 23:45–00:20 IST | IRCTC maintenance window: no train search or availability check (HTTP 503) |
| `RAILKIT_SUPPORTED_QUOTAS` | `GN,TQ` | quotas RailKit accepts (docs/09 Q16); drop `TQ` to disable Tatkal |
| `TATKAL_*` | 1 day, 10:00 / 11:00 | booking window relative to the train's origin date (IST) |
| `SEARCH_EXECUTION_MODE` | `async` | `202 Accepted` + polling; `sync` for tests |

## Repository layout

```text
backend/            FastAPI modular monolith (app/), Alembic migrations, tests
frontend/web/       Next.js web/PWA client (same-origin /api proxy to the backend)
infrastructure/     PostgreSQL init scripts (least-privilege runtime role)
docs/               Product, architecture, decisions, provider contract log
compose.yaml        Local stack (PostgreSQL, Redis; app services under the "app" profile)
```

## Status

| Milestone | State |
|---|---|
| 1. Repository and foundation | ✅ done |
| 2. Provider contract (mock + RailKit adapter, fixtures) | ✅ done — verified live 2026-11-14 (docs/09 §5) |
| 3. Domain and optimizer | ✅ done |
| 4. Persistence and caching | ✅ done |
| 5. API orchestration | ✅ done |
| 6. Frontend | ✅ done |
| 7. Hardening | ✅ done (see `docs/10_OPERATIONS_RUNBOOK.md`) |

Verification at the time of writing (2026-11-15, after fair budget allocation — docs/08 §6b):
backend 467 unit/API tests + 12 PostgreSQL/Redis integration tests (ruff, mypy `--strict`),
frontend 44 Vitest tests, 22 Playwright tests (desktop + mobile, axe WCAG 2.1 AA).

## Known limitations

- Searches run as in-process background tasks of the backend replica that received them
  (state is in PostgreSQL, so any replica can answer polling). A replica that dies abandons its
  searches; they are reported `FAILED / INTERRUPTED` after the grace period. A dedicated worker
  queue (e.g. Arq on Redis) can replace the executor without touching the orchestrator.
- No user accounts yet: API rate limits are per client IP (see runbook §4 for proxy trust).
- Station search calls the provider (≥ 3 characters, cached). Code-like input (3–5 letters or
  digits, e.g. `TVCN`) also gets an exact code lookup, because RailKit's name search does not match
  codes; that costs at most one extra request per new code (results, including "not found", are
  cached).
- npm reports 8 moderate advisories, all in the ESLint toolchain (dev-only, `minimatch` ReDoS);
  production dependencies have none (`npm audit --omit=dev`).

- RailKit's Free plan only accepts SDK-signed requests; the backend needs a plan with
  "API endpoint access". A few contract details remain unverified (docs/09 §5: Q10, Q12, Q13).
- Premium Tatkal (`PT`) is not offered: RailKit's seat availability rejects it (docs/09 Q16).
  Tatkal windows are RailRoute configuration, not provider data; a quota that was not open is not
  re-checked automatically.
- RailKit's train search matches station clusters (NDLS also finds NZM/DEE trains). Recommendations
  always use the exact searched stations; the UI offers a search for each train's own stations.
- RailKit's caching, storage and commercial-redistribution terms are unconfirmed; this is a
  launch gate (docs/06 §8).


## Future

1. Advanced Journey Optimization


  - Expand the core optimization engine to support more advanced journey-planning scenarios.
  - Multiple-segment ticket combinations.
  - Automatically identify optimal intermediate stations.
  - Compare different trains and travel dates.
  - Support multiple travel classes and reservation quotas.
  - Eventually support journeys involving different trains, with realistic transfer times   between connecting trains.

2. AI-Powered Availability Intelligence

  - Introduce intelligent features that help passengers make better booking decisions using historical railway availability data and predictive analytics.
  - Historical waitlist confirmation analysis.
  - Predict the probability of waitlist confirmation.
  - Identify the best time to book tickets.
  - Compare availability trends across different travel dates.
  - Recommend alternative trains or travel dates.
  - Develop an independent ML-based prediction model using historical availability and booking outcome data.

Important: Actual ticket availability and predicted confirmation probability must always be treated as separate concepts. Predictions should never be presented as guaranteed outcomes. Initially, RailKit's prediction data can be used, with the possibility of developing an independent prediction model in the future.

3. Complete Railway Travel Assistant

  - Expand the application beyond ticket availability optimization by integrating additional railway information and passenger services.
  - Live train running status.
  - Platform and station information, wherever reliable data is available.
  - PNR status tracking.
  - Train delay alerts and journey notifications.
  - Station facilities and nearby services.

4. Smart Passenger Features

  - Introduce personalized features to improve the overall passenger experience and make the platform useful beyond individual searches.
  - Save favourite routes.
  - Notify users when ticket availability improves.
  - Track multiple booking PNRs belonging to a single journey.
  - Provide a consolidated itinerary for journeys involving multiple tickets.
  - Display total journey fare and segment-wise ticket costs.
  - Explain booking risks and limitations associated with separate tickets.

5. Booking Ecosystem Integration

  - Build integrations with authorized railway booking platforms and travel service providers to create a smoother journey-planning and booking experience.
  - Provide deep links to authorized ticket-booking platforms.
  - Partner with authorized railway information providers.
  - Potentially integrate permitted ticket-booking APIs.
  - Explore affiliate and referral-based revenue opportunities.
  - Eventually introduce a booking workflow, subject to the required authorization and availability of official integrations.

6. Business and Enterprise Opportunities

  - Explore commercial opportunities by making the RailRoute optimization engine available to other businesses and travel platforms.
  - Provide API access to travel companies.
  - Offer white-label journey optimization solutions for travel agencies.
  - Develop analytics dashboards for travel businesses.
  - Introduce subscription plans for frequent travellers.
  - Establish partnerships with travel platforms and relevant service providers.