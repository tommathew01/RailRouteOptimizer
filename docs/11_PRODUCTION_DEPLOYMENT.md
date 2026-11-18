# 11 — Production Deployment

How to host RailRoute publicly: readiness assessment, platform comparison, the chosen architecture
(Render, defined in `render.yaml`), costs, a step-by-step guide, production variables, a
verification checklist and known limits. Written 2026-11-18; prices were read from the providers'
own pages that day and change over time — re-check before budgeting.

Companion documents: `10_OPERATIONS_RUNBOOK.md` (operating rules), `08_IMPLEMENTATION_PLAN.md`
D-37 (this decision).

---

## 1. What the application needs (verified in the code)

| Concern | What the code does | Hosting requirement |
|---|---|---|
| Frontend | Next.js 16 (App Router, Cache Components), `output: "standalone"`, Dockerfile → `node server.js` on `PORT` | A container or Node host; one public HTTPS service |
| Browser → backend | Only the same-origin proxy `/api/v1/*` (route handler). `BACKEND_INTERNAL_URL` is read **at runtime** | Backend can (and should) stay **private**; no CORS needed |
| Backend | FastAPI, one uvicorn process per container, Dockerfile (uv, Python 3.12), `/api/v1/health/live` and `/health/ready` | An always-on container |
| Optimization | `POST /journeys/optimize` → **202 Accepted**; the search runs as an in-process asyncio task (≤ `SEARCH_DEADLINE_SECONDS` = 90 s); the browser polls `GET /journeys/{id}` every 1.5 s. Every HTTP request is short (proxy timeout 30 s) | **No long HTTP requests**, so platform request timeouts do not matter — but the backend must **not scale to zero or sleep** (background tasks need a running process) |
| State | Searches, results, observations, provider usage in **PostgreSQL**; cache, single-flight locks, provider quota counters, API rate limits and stop-search flags in **Redis** | Managed PostgreSQL + Redis-compatible store. `ENVIRONMENT=production` refuses to start without both |
| Stop search | Shared Redis flag + immediate in-process stop; queued provider calls are withdrawn (D-35) | Works across replicas (verified, §10) |
| Maintenance window | 23:45–00:20 IST enforced in the backend on timezone-aware instants (`Asia/Kolkata`) (D-31) | Any server timezone (containers run in UTC) |
| RailKit | Backend only (`RAILKIT_API_KEY`); global quota guard in Redis checks every HTTP attempt incl. retries | Secret store; Redis must never evict quota counters |
| Schema | Alembic migrations (`alembic upgrade head`), schema-owner role | A pre-deploy step |
| Retention | `python -m app.cli purge` (daily) | A scheduled job |
| Persistent disk | None (no uploads, no local files) | — |
| Authentication | **None yet** (anyone with a results link can view or stop that search) | Launch gate, §11 |

**Multi-user safety review.** Per-search state lives in a `SearchContext` keyed by a random UUID;
stop flags and the in-process registry are keyed by search id; caches are keyed by
train/date/stations/class/quota and shared deliberately; a refusal or stop inside the shared
in-process single-flight is never inherited by another user's search (D-35). Process-wide limits
are intentional and fair: `RAILKIT_MAX_CONCURRENCY` (provider connections per process),
`MAX_CONCURRENT_SEARCHES` (further searches wait in a queue), the global quota guard, and
per-client-IP API rate limits. No mutable global per-user state was found.

## 2. Readiness before this work, and what was changed

| Finding | Change (all small, no architectural change) |
|---|---|
| Both apps already had production Dockerfiles, health endpoints, env-based config and a runbook | — |
| CI (`.github/workflows/ci.yml`) only ran on pushes to `main`; the branch is `master`, so pushes were never tested | Runs on `master` and `main` |
| Render links services as `host:port`; the proxy required a full URL | `backendBaseUrl()` adds `http://` (private network) |
| A deploy or restart **cancelled** running searches (in-process tasks) | `SEARCH_SHUTDOWN_GRACE_SECONDS`: on SIGTERM, running searches finish first (production 95 s; default 0 keeps local behaviour) |
| Operator endpoints (`/metrics`, `/ops/*`) were unreachable through the public URL (the proxy strips `Authorization`), so quota usage could not be checked with a private backend | The proxy forwards `Authorization` **only** for `/api/v1/metrics` and `/api/v1/ops/*` (still Bearer-token protected) |
| The client IP for rate limits depends on how the platform builds `X-Forwarded-For` (not documented by Render) | `GET /api/v1/ops/client-address` (token) shows the chain, to set `TRUSTED_PROXY_HOPS` (§6 step 6) |
| A Redis eviction policy of `allkeys-lru` could silently delete quota counters | `render.yaml` sets `noeviction` (all keys already expire) |
| Managed PostgreSQL has a single owner user; the app is designed to run as a DML-only role | `infrastructure/postgres/managed-app-role.sql` (optional hardening, §7) |
| No platform configuration | `render.yaml` Blueprint |

## 3. Hosting options compared

Monthly prices in USD unless noted, for this application's shape (2 small containers +
PostgreSQL + Redis + a daily job).

| | **Render** (recommended) | Railway | Fly.io | DigitalOcean / Hetzner VPS + Docker Compose | AWS (ECS Fargate + RDS + ElastiCache) |
|---|---|---|---|---|---|
| Ease for a hosting beginner | High — one Blueprint file, dashboard | High | Medium (CLI, machines, regions) | Low — you run the server | Low |
| Est. monthly cost | **≈ $30** (§5) | ≈ $5 plan incl. $5 usage, then ≈ $20/vCPU-month + $10/GB-RAM-month → ≈ $10–20 | Machines from $3.69 (512 MB) each; Managed Postgres from **$38** | DO 2 GB droplet $12 (+20–30 % for backups); Hetzner from €5.49 (Singapore location exists) | ≈ $70+ (rough estimate: load balancer, RDS, ElastiCache) |
| Production-usable free tier | **No** — free web services sleep after 15 min (≈ 1 min cold start); no free private services or cron jobs; free Postgres expires after 30 days; free Key Value loses data on restart | **No** — Free: $1/month credit, 0.5 GB per service | **No** — 7-day trial with $1 credit | No | Free-tier credits only |
| Always-on backend (background searches) | Yes (paid instances) | Yes | Yes if auto-stop is disabled | Yes | Yes |
| Next.js | Docker image as is | Docker image as is | Docker image as is | Compose as is | Docker image as is |
| Managed Postgres / Redis | Yes / Yes (Key Value) | Template containers on volumes | Postgres managed (expensive) / Redis via partner | You run them (already in `compose.yaml`) | Yes / Yes |
| Private networking (backend not public) | Yes, all plans | Yes | Yes | Yes (Docker network) | Yes (VPC) |
| Pre-deploy migrations, cron jobs | Yes / Yes | Yes / Yes | Release command / scheduled machines | Scripts / cron | Tasks / EventBridge |
| GitHub auto-deploy, failed deploy keeps old version, rollbacks | Yes / Yes / Yes | Yes | Via GitHub Actions | You build it (e.g. Actions + SSH) | CodePipeline etc. |
| Region near India | Singapore | Singapore | Mumbai/Singapore (India egress $0.12/GB) | DO Bangalore; Hetzner Singapore | Mumbai |
| Growth path | Bigger plans, more backend instances, Postgres HA (Pro workspace) | Usage-based scaling | Global scaling | Bigger box; manual HA | Unlimited, most work |

Vercel can host only the Next.js part (the FastAPI backend would still need another platform);
splitting providers adds a second bill, cross-provider latency and configuration without benefit
for this app.

**Why Render.** It maps one-to-one onto the existing architecture — a public Next.js container, a
private FastAPI container, managed PostgreSQL, managed Redis-compatible store, a cron job and a
pre-deploy migration — with no code redesign. A failed build, migration or start leaves the
previous version serving; rollbacks are one click; TLS is automatic; logs and metrics are in the
dashboard; Singapore is close to India. It costs about 3–5× a bare VPS, which buys not having to
patch, secure, back up and monitor a server yourself — the right trade for a beginner running a
commercial service. The cheapest reliable alternative is a VPS with the existing `compose.yaml`
plus a TLS reverse proxy (§12); nothing in the application ties it to Render.

## 4. Architecture

```text
User's browser
   │  HTTPS (Render-managed TLS certificate; your domain)
   ▼
railroute-web — Next.js standalone (public web service, Singapore)
   │  /api/v1/*  same-origin proxy · BACKEND_INTERNAL_URL = backend host:port
   │  Render private network (plain HTTP inside Render)
   ▼
railroute-backend — FastAPI (private service, not reachable from the internet)
   ├── railroute-db     PostgreSQL 18 (searches, results, observations, usage)   private only
   ├── railroute-cache  Key Value / Redis (cache, quota guard, rate limits,      private only
   │                    single-flight, stop-search flags) — noeviction
   └── RailKit REST API  (HTTPS, x-api-key from the backend only)

railroute-retention — daily cron (backend image): python -m app.cli purge → railroute-db
```

The browser never sees the backend address or the RailKit key: it calls the Next.js origin,
whose route handler forwards an allowlisted set of headers to the private backend.

## 5. Estimated monthly cost (Render, Singapore, Hobby workspace)

| Resource (`render.yaml`) | Plan | USD / month |
|---|---|---|
| railroute-web | `0.5c-512mb` | 7 |
| railroute-backend | `0.5c-512mb` | 7 |
| railroute-db | `0.1c-256mb` + storage $0.30/GB | 6 + ≈ 0.30–1.50 |
| railroute-cache | `256mb` | 10 |
| railroute-retention | cron, ≈ 1 min/day at $0.00016/min | < 0.01 |
| Workspace | Hobby: $0, 5 GB bandwidth, 500 build minutes (then $0.15/GB) | 0 |
| **Total** | | **≈ $30–32** + domain (≈ $10–15 per year) |

Measured sizes: one result snapshot (10 recommendations) ≈ 46 KB uncompressed, all frontend
JavaScript ≈ 0.8 MB, polled every 1.5 s while running → roughly 1–3 MB per search session, so
5 GB covers a few thousand searches. **RailKit quota is the binding limit long before bandwidth:**
at `SEARCH_MAX_AVAILABILITY_REQUESTS=100`, a 5,500-request plan allows ≈ 55 full searches a month
(cache hits are free). Move to the Pro workspace ($25) when you need team members, more
bandwidth or build minutes.

## 6. Deploying, step by step

**Accounts you need:** GitHub (the repository), Render (sign in with GitHub), a domain registrar
(any; e.g. one selling `.in` or `.com`), and a RailKit plan that includes **API endpoint access**
(the Free plan is SDK-only — runbook §8).

1. **Commit and push.** Render deploys what is on GitHub (`master`). Push all work, then confirm
   the CI workflow is green: GitHub → repository → *Actions*.
2. **Protect `master`** (recommended): GitHub → *Settings → Branches → Add rule* for `master` →
   require the CI status checks to pass. Never commit `.env` (it is in `.gitignore`).
3. **Create the services from the Blueprint.** Render dashboard → *New → Blueprint* → connect the
   GitHub repository (grant access to this repository only) → branch `master`. Render reads
   `render.yaml` and lists five resources. It asks for:
   - `RAILKIT_API_KEY` — from the RailKit dashboard. Use a **separate key (or plan) from local
     development**, or local experiments will consume production quota;
   - `PROVIDER_MONTHLY_REQUEST_LIMIT` / `PROVIDER_WINDOW_REQUEST_LIMIT` — slightly below your
     plan, minus anything else using the same key.

   Add a payment method, then *Apply*. Order of events: database and Key Value are created; the
   backend image is built, `alembic upgrade head` runs, the backend starts; the frontend is built
   and becomes live at `https://railroute-web-<random>.onrender.com`; the cron job is scheduled.
   Watch each service's *Logs* tab. If any step fails, the previous version (none, on the first
   deploy) keeps serving.
4. **First checks** (replace `$URL`; none of these spend RailKit quota):
   ```bash
   curl -sI $URL/                       # 200, with Strict-Transport-Security
   curl -s  $URL/api/v1/health/ready    # {"status":"ready","checks":{"redis":"ok","database":"ok"}}
   curl -s  $URL/api/v1/meta | head -c 300   # "data_mode":"LIVE"
   ```
5. **Read the operator token**: backend service → *Environment* → `METRICS_TOKEN` (generated).
   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" $URL/api/v1/ops/provider-quota
   ```
6. **Calibrate the client address used for rate limits** (Render's `X-Forwarded-For` layout is
   not documented, so measure it):
   ```bash
   curl -s ifconfig.me    # your public IP
   curl -s -H "Authorization: Bearer $TOKEN" -H "X-Forwarded-For: 203.0.113.99" \
        $URL/api/v1/ops/client-address
   ```
   Choose `TRUSTED_PROXY_HOPS` so that `client_address` is **your IP** and never the fake
   `203.0.113.99` (count positions from the right of `x_forwarded_for`; 1 = last). Set it on the
   backend (*Environment*), which redeploys. Re-check after adding Cloudflare or any other proxy.
7. **Smoke-test a real search** in the browser (this spends RailKit quota — one search): stations
   → trains → select one train → *Find segment combinations*; then start another and press
   *Stop search*. Use the checklist in §9.
8. **Custom domain and HTTPS** (§8).
9. **Monitoring** (§10).
10. **Optional hardening — least-privileged database role** (§7).

## 7. Production environment variables

Set by `render.yaml` unless marked *you set*. Everything else uses the defaults in
`backend/app/core/config.py`, documented in `.env.example`.

| Service | Variable | Value / source | Secret |
|---|---|---|---|
| backend, cron | `ENVIRONMENT` | `production` (requires DB, Redis, RailKit; refuses mock data) | no |
| backend, cron | `RAILWAY_PROVIDER` | `railkit` | no |
| backend, cron | `LOG_LEVEL`, `LOG_JSON` | `INFO`, `true` | no |
| backend, cron | `DATABASE_URL` | Render Postgres internal connection string | **yes** (managed by Render) |
| backend, cron | `REDIS_URL` | Render Key Value internal connection string | **yes** (managed by Render) |
| backend | `RAILKIT_API_KEY` | *you set* (cron reuses it only to pass config validation) | **yes** |
| backend | `PROVIDER_MONTHLY_REQUEST_LIMIT`, `PROVIDER_WINDOW_REQUEST_LIMIT` | *you set*, below your plan | no |
| backend | `METRICS_TOKEN` | generated by Render | **yes** |
| backend | `SEARCH_MAX_AVAILABILITY_REQUESTS` | `100` | no |
| backend | `RAILKIT_MAX_CONCURRENCY`, `MAX_CONCURRENT_SEARCHES` | `4`, `4` | no |
| backend | `SEARCH_SHUTDOWN_GRACE_SECONDS` | `95` (with `maxShutdownDelaySeconds: 120`) | no |
| backend | `TRUSTED_PROXY_HOPS` | `1`, then calibrated (§6 step 6) | no |
| backend | `MIGRATION_DATABASE_URL` | only after hardening (below) | **yes** |
| web | `BACKEND_INTERNAL_URL` | backend `host:port` on the private network | no |
| web | `PORT` | `3000` | no |

`CORS_ALLOWED_ORIGINS` needs no change: browsers only call the same-origin proxy and the backend
is not reachable from the internet. Nothing starting with `NEXT_PUBLIC_` exists, so no
configuration is baked into the browser bundle.

**Least-privileged runtime role (recommended).** The Blueprint starts with Render's single owner
user. To run the app as a DML-only role:

1. Database → inbound IP rules (*Access Control*): temporarily allow your IP; copy the **External**
   connection string.
2. `psql "<external URL>" -v ON_ERROR_STOP=1 -v app_user=railroute_app -v app_password='<long random>' -f infrastructure/postgres/managed-app-role.sql`
   (verified locally: the role can read/write rows, `CREATE TABLE` fails with "permission denied").
3. In `render.yaml` (backend and cron): change `DATABASE_URL` to `sync: false` and add
   `MIGRATION_DATABASE_URL` with `fromDatabase … connectionString`; push. Then set `DATABASE_URL`
   in the dashboard to the internal URL with `railroute_app` and its password. Remove your IP
   from the database allow list again.

**Secrets hygiene.** `.env` and `.env.*` are git-ignored and excluded from both Docker images;
`render.yaml` contains no secret values; the RailKit key exists only in the backend's environment
and is redacted from logs (tested). Rotate the key in RailKit and update it in Render if it is ever
exposed.

## 8. Domain, HTTPS, DNS

1. Buy a domain at any registrar.
2. Render → `railroute-web` → *Settings → Custom Domains* → add `example.in` and
   `www.example.in`. Render shows the exact DNS records to create (typically a `CNAME` for `www`
   pointing at `railroute-web-<random>.onrender.com`, and for the apex an `ALIAS`/`ANAME`/flattened
   `CNAME` or the `A` record Render specifies). Add them at the registrar; DNS can take minutes to
   hours.
3. Render issues and renews the TLS certificates automatically once DNS resolves. Pick one
   canonical host (e.g. `www`) and let the other redirect to it.
4. The backend needs no domain (private). HSTS is already sent by the frontend in production.
5. If you later put Cloudflare's proxy in front of Render, re-run §6 step 6.

## 9. Production verification checklist

Mark each after checking on the live URL. Items marked ⚑ spend RailKit quota.

| # | Check | How |
|---|---|---|
| 1 | Frontend loads over HTTPS on the domain; `www`/apex redirect | Browser; `curl -sI` |
| 2 | Backend reachable only through the frontend | `/api/v1/health/ready` via the site works; the backend has no public URL in Render |
| 3 | `data_mode: LIVE`, demo banner absent | `/api/v1/meta`, home page |
| 4 | Station search returns real stations ⚑ | Type a station name |
| 5 | Train lookup works ⚑ | Stations + date → *Find trains* |
| 6 | Combination preview shows counts and budget | Select a train |
| 7 | Search runs, progress updates, results appear ⚑ | *Find segment combinations* |
| 8 | Refreshing the results page keeps the results | Reload `/results/<id>` |
| 9 | Stop search stops the provider calls and keeps results ⚑ | Start a search, press *Stop search*; `ops/provider-quota` stops increasing |
| 10 | Two searches in two browsers do not interfere ⚑ | Stop one; the other completes |
| 11 | Maintenance window | Between 23:45–00:20 IST the UI explains it and `POST /api/v1/trains/search` returns `503 RAILWAY_MAINTENANCE` |
| 12 | No credential reaches the browser | DevTools → Network/Sources: search for the key's first characters — nothing; responses never contain it |
| 13 | Quota guard counts | `ops/provider-quota` matches the RailKit dashboard for the same period |
| 14 | Rate-limit address is the real client | §6 step 6 |
| 15 | Deploy without interrupting a search | Start a search, push a trivial commit; the search still completes |
| 16 | Retention job runs | `railroute-retention` → *Logs* next day |

## 10. Monitoring (no paid services required)

- **Render dashboard**: per-service logs (search, live tail), CPU/memory graphs, deploy history,
  e-mail notifications for failed deploys. The web service's health check is `/`.
- **External uptime check** (any free uptime monitor): `GET https://<domain>/` and
  `GET https://<domain>/api/v1/health/ready` every 5 minutes, alert by e-mail.
- **RailKit quota**: `GET /api/v1/ops/provider-quota` with the token (window, month, back-off);
  compare weekly with the RailKit dashboard. Searches end `PARTIAL_BUDGET /
  PROVIDER_QUOTA_GUARD_REACHED` when the guard stops spending.
- **Log patterns** (JSON logs): `provider call refused by quota guard`, `outcome` = `AUTH` /
  `RATE_LIMITED` / `TIMEOUT` / `UPSTREAM`, `search failed`, `invalid provider response` — the
  meaning and action for each are in runbook §8.
- **Metrics**: `/api/v1/metrics` (Prometheus, token) is ready for a hosted Prometheus/Grafana
  later; not needed at first.
- **Restarts**: a restarted backend first finishes running searches (grace 95 s); searches that
  still could not finish are reported `FAILED / INTERRUPTED` with their partial results; stale ones
  are reaped automatically (runbook §3).

**Verified locally with the production images (2026-11-18)**: both Docker images, PostgreSQL with
the managed-role script (DML only), Redis with `noeviction`, two backend replicas and the frontend
given a scheme-less `host:port` backend address. Results: all 32 Playwright end-to-end tests
passed through the real proxy; a search on replica B stopped 0.5 s after the stop was sent to
replica A (only the 2 in-flight requests completed, results kept); another user's search on the
same replica completed normally; SIGTERM during a search let it finish (`COMPLETE`) before the
process exited. **Not yet verified**: anything on Render itself, the live RailKit integration in
production, and the custom domain — use §9 after deploying.

## 11. Scalability and reliability concerns

| Concern | Impact | Mitigation / next step |
|---|---|---|
| **RailKit quota** | ≈ 55 full searches/month on a 5,500-request plan at 100 requests/search | Keep the budget modest; caching helps repeat searches; larger plan before launch |
| **No user accounts** | Anyone can run searches; anyone with a results link can view or stop that search; abuse could exhaust quota (the guard stops spending, but legitimate users are then blocked) | Per-IP rate limits exist; add accounts or a CAPTCHA and per-user quotas before wide public launch (runbook §9) |
| One backend instance | A crash interrupts running searches (reported, partial results kept) | Add a second instance when needed — multi-replica behaviour verified; quota guard, rate limits and stop flags are shared through Redis |
| In-process search execution | ≤ `MAX_CONCURRENT_SEARCHES` per instance, queue lost on crash | Scale instances; later a Redis-backed worker queue (D-06) without changing the orchestrator |
| Migrations vs rollbacks | A Render rollback does not undo a migration | Keep migrations backward compatible (add columns before using them; drop later) |
| Postgres 256 MB plan | Fine for small volumes; raw payloads purged after 14 days, searches after 90 | Upgrade the plan when the dashboard shows memory/connection pressure; enable backups/PITR per plan |
| Platform lock-in | Low: standard containers and `compose.yaml` | Move to a VPS or cloud with the same images |
| Launch gates (unchanged) | RailKit written terms for commercial use, caching and display; privacy policy and terms; security review | Runbook §9 |

## 12. Lower-cost alternative: one VPS with Docker Compose

If cost matters more than convenience: a 2 GB VPS (DigitalOcean Bangalore $12, Hetzner Singapore
from about €5.49) running the existing `compose.yaml` (`--profile app`) plus a TLS reverse proxy
such as Caddy in front of the frontend only (it obtains certificates automatically and sets
`X-Forwarded-For`; keep `TRUSTED_PROXY_HOPS=1`), with `SEARCH_SHUTDOWN_GRACE_SECONDS=95` and a
longer `stop_grace_period` for the backend. You then own OS updates, firewall (open 80/443 only),
database backups, uptime monitoring, and the deploy script (e.g. GitHub Actions → SSH →
`docker compose pull && up -d`). Not implemented here because it trades money for operational work
the Render setup avoids.
