# RailRoute Optimizer

Railway availability discovery and **same-train segment optimization** for Indian Railways.

When a direct reservation is waitlisted or unavailable, RailRoute checks shorter
station-to-station reservations on the **same train, date, class and General (GN) quota** and
finds combinations of **1–4 separate tickets** that cover the whole journey, e.g.
`TIR → SRR` + `SRR → TCR` + `TCR → TVC`.

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

Everything in one command instead: `docker compose --profile app up -d --build`.

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
| `SEARCH_MAX_AVAILABILITY_REQUESTS` | `30` | provider availability calls per search (server-enforced) |
| `PROVIDER_MONTHLY_REQUEST_LIMIT` | `50` | global guard; set to your RailKit plan |
| `AVAILABILITY_DATE_POLICY` | `SEGMENT_BOARDING_DATE` | date sent for segments boarding after midnight (docs/08 D-02) |
| `AVAILABILITY_CACHE_TTL_SECONDS` | `120` | pending RailKit caching terms |
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

Verification at the time of writing: backend 329 unit/API tests + 11 PostgreSQL/Redis integration
tests (ruff, mypy `--strict`), frontend 25 Vitest tests, 12 Playwright tests (desktop + mobile,
axe WCAG 2.1 AA), and the same Playwright suite against the Docker Compose stack.

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
- RailKit's train search matches station clusters (NDLS also finds NZM/DEE trains). Recommendations
  always use the exact searched stations; the UI offers a search for each train's own stations.
- RailKit's caching, storage and commercial-redistribution terms are unconfirmed; this is a
  launch gate (docs/06 §8).
