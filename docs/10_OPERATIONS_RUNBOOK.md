# 10 — Operations Runbook

For engineers deploying and operating RailRoute. Everything here reflects the code as built;
where behaviour depends on an unverified RailKit contract, it says so and points to
`09_RAILKIT_CONTRACT_VERIFICATION.md`.

## 1. Topology

```text
Browser ──HTTPS──▶ Load balancer / reverse proxy (TLS, sets X-Forwarded-For)
                        │
                        ▼
             Next.js standalone server (frontend/web)      ← only public component
               └─ /api/v1/* same-origin proxy (route handler)
                        │  private network
                        ▼
             FastAPI backend (uvicorn, app.asgi:app)       ← never exposed publicly
               ├─ PostgreSQL  (searches, observations, recommendations, usage, routes)
               ├─ Redis       (cache, single-flight locks, provider quota counters, API rate limits)
               └─ RailKit REST API (x-api-key, backend only)
```

| Component | Image / command | Health |
|---|---|---|
| Migrations | `alembic upgrade head` (backend image), **schema-owner role** | exits 0 |
| Backend | `uvicorn app.asgi:app --no-proxy-headers --no-server-header` | `GET /api/v1/health/live`, `GET /api/v1/health/ready` (DB + Redis) |
| Frontend | `node server.js` (Next.js standalone) | `GET /` |

Local equivalent: `docker compose --profile app up -d --build` (see `compose.yaml`).

## 2. Configuration

Every variable is documented in `.env.example` and validated at startup (`app/core/config.py`).
Startup fails fast on invalid configuration.

**Required in production** (`ENVIRONMENT=production` refuses to start otherwise):

| Variable | Notes |
|---|---|
| `RAILWAY_PROVIDER=railkit`, `RAILKIT_API_KEY` | Production refuses the mock provider |
| `DATABASE_URL` | Least-privileged runtime role (DML only) |
| `MIGRATION_DATABASE_URL` | Schema-owner role, used only by the migration job |
| `REDIS_URL` | Shared quota guard, cache and rate limits across replicas |
| `PROVIDER_MONTHLY_REQUEST_LIMIT`, `PROVIDER_WINDOW_REQUEST_LIMIT` | Set slightly **below** your RailKit plan (Free 50/100, Pro 5000/200, Advance 10000/600 per month / per 10 min) |
| `METRICS_TOKEN` | Without it `/api/v1/metrics` and `/api/v1/ops/provider-quota` return 404 outside development |
| `CORS_ALLOWED_ORIGINS` | Browser traffic is same-origin via the proxy; keep this to your web origin |
| `TRUSTED_PROXY_HOPS` | See §4 |
| `BACKEND_INTERNAL_URL` (frontend) | Read at runtime, so one frontend image serves all environments |

**Cache TTLs** (`*_CACHE_TTL_SECONDS`) are conservative defaults. RailKit's caching and storage
terms are unconfirmed (launch gate, doc 06 §8); do not raise them before written confirmation.

## 3. Deploying

1. Run the migration job with `MIGRATION_DATABASE_URL` (owner role). The PostgreSQL init script
   (`infrastructure/postgres/initdb`) grants the runtime role DML on every table the owner creates;
   on managed PostgreSQL apply the same `ALTER DEFAULT PRIVILEGES` statements once.
2. Roll out backend replicas. Each replica on startup marks searches that have shown **no progress
   for `SEARCH_DEADLINE_SECONDS` + 5 minutes** as `FAILED / INTERRUPTED`; searches running on other
   healthy replicas are untouched, so rolling deploys are safe. Polling a stale search also reaps
   it, so a crashed replica's searches resolve even if it never restarts. Partial results already
   found stay visible.
3. Roll out the frontend.
4. Check `GET /api/v1/health/ready` → `{"status":"ready"}` and `GET /api/v1/meta` → `data_mode: LIVE`.

## 4. Client addresses and rate limits

Per-client API limits (`API_RATE_LIMIT_*`) key on a hash of the client IP. The backend picks the
address `TRUSTED_PROXY_HOPS` entries from the right of `X-Forwarded-For`.

Measured behaviour of the Next.js proxy: when the request has no `X-Forwarded-For`, Next sets it to
the socket peer; when the request already has one, it is passed through **unchanged**. Therefore:

* **Production** — put a load balancer that appends or overwrites `X-Forwarded-For` in front of
  Next, keep the backend on a private network, and set `TRUSTED_PROXY_HOPS=1`.
* **Compose (`app` profile)** — the backend defaults to `1` (`COMPOSE_TRUSTED_PROXY_HOPS`) because
  it is only reached through Next. Without a load balancer a client can spoof the header and evade
  the *API* rate limit — acceptable on localhost, not on the internet.
* **Backend run directly** (development) — `TRUSTED_PROXY_HOPS=0`.

The RailKit budget is protected independently of client identity (§5), so spoofing can never
raise provider spend beyond the configured guard.

## 5. Provider budget controls

| Control | Scope | Behaviour when hit |
|---|---|---|
| `SEARCH_MAX_AVAILABILITY_REQUESTS` | one search: provider attempts, **retries included** (D-28) | Search finishes `PARTIAL_BUDGET` with what it found; a failed check that cannot be retried within it stays "not checked" |
| `SEARCH_MAX_TRAINS` / `SEARCH_MAX_CLASSES` | one search | `400 TOO_MANY_TRAINS` / `TOO_MANY_CLASSES` before any provider call (never truncated) |
| `PROVIDER_WINDOW_REQUEST_LIMIT` / `PROVIDER_WINDOW_SECONDS` | all replicas (Redis) | Calls refused before reaching RailKit; searches end `PARTIAL_BUDGET / PROVIDER_QUOTA_GUARD_REACHED` |
| `PROVIDER_MONTHLY_REQUEST_LIMIT` | all replicas, IST calendar month | Same as above. Your RailKit billing cycle may differ: keep headroom |
| RailKit 429 | all replicas | Shared back-off for `Retry-After` or `PROVIDER_RATE_LIMIT_BACKOFF_SECONDS` |
| Redis unavailable | — | Provider calls **fail closed** (no unmetered spending) |

Every HTTP attempt counts against the guard, including retries (`RAILKIT_MAX_RETRIES`,
timeouts/5xx only); during a search each retry is also paid from that search's budget. Worst case
per search: 1 train search + `SEARCH_MAX_TRAINS` routes + `SEARCH_MAX_AVAILABILITY_REQUESTS`
availability attempts. Current usage: `GET /api/v1/ops/provider-quota` with
`Authorization: Bearer $METRICS_TOKEN`.

Docker and `make backend` read the same root `.env`; the Compose backend forwards every
application setting (docs/08 D-30). After changing `.env` or code, recreate the stack with
`docker compose --profile app up -d --build`.

## 6. Observability

* Logs: one JSON object per line with `request_id`, `search_id`, provider, endpoint, outcome,
  latency. API keys, URL passwords and sensitive header values are redacted.
* Metrics (`GET /api/v1/metrics`, Prometheus): `railroute_provider_requests_total{endpoint,outcome}`,
  `railroute_provider_latency_seconds`, `railroute_provider_quota_refusals_total{reason}`,
  `railroute_cache_lookups_total{kind,result}`, `railroute_provider_malformed_responses_total`,
  `railroute_searches_total{completeness}`, `railroute_search_duration_seconds`,
  `railroute_search_recommendations`, `railroute_search_availability_requests` (attempts per
  search, retries included), `railroute_search_availability_retries_total{result=made|refused}`,
  `railroute_search_combinations_not_reached`, `railroute_prediction_coverage_ratio`,
  `railroute_active_searches`. A non-zero `combinations_not_reached` means users select more
  combinations than the budget covers.

Suggested alerts: 429 or `AUTH` outcomes > 0 in 5 min; quota refusals > 0; malformed responses
> 0 (contract drift); `PARTIAL_*` share > 50 % over an hour; `/health/ready` failing.

## 7. Data retention

`python -m app.cli purge` (or `make purge`) applies the policy, using the runtime role:

| Data | Default | Flag |
|---|---|---|
| Raw provider payloads (stripped, row kept) | 14 days | `--raw-payload-days` |
| Searches + their runs and recommendations; unreferenced observations | 90 days | `--search-days` |
| Provider usage rows (billing reconciliation) | 400 days | `--usage-days` |

Use `--dry-run` to preview. Unfinished searches are never deleted. Schedule it daily (cron,
Kubernetes CronJob, etc.). Align these values with RailKit's storage terms once confirmed.

## 8. Incident playbooks (doc 06 §7)

| Symptom | Meaning | Action |
|---|---|---|
| Provider log `error="Missing SDK signature headers…"` with `status_code=403` | The RailKit plan does not allow direct REST access (Free plan is SDK-only) | Upgrade to a plan with "API endpoint access" |
| `outcome="AUTH"`, users get `503 PROVIDER_UNAVAILABLE`, searches `PARTIAL_PROVIDER_ERRORS / PROVIDER_AUTH_ERROR` | Key invalid or inactive | Check the key in the RailKit dashboard and secret store; rotate if exposed. The client stops calling for the rest of a search — do not loop restarts |
| `outcome="RATE_LIMITED"`, `PROVIDER_RATE_LIMITED` | RailKit 429 (RailKit uses this for "usage limit exceeded") | Shared back-off is automatic. Check plan usage; lower the guard limits or buy a request pack |
| Quota refusals with `reason="MONTHLY_LIMIT"` / `"WINDOW_LIMIT"` | Our guard stopped spending | Expected at the configured cap. Raise only if the plan allows |
| `reason="GUARD_UNAVAILABLE"` | Redis unreachable | Restore Redis; provider calls stay blocked until then (by design) |
| `outcome="TIMEOUT"` / `"UPSTREAM"` spikes | RailKit slow or failing | Retries are bounded; searches return partial results. Consider lowering concurrency |
| `railroute_provider_malformed_responses_total` rising | Payload shape changed | Affected segments are `INVALID_RESPONSE`/`UNKNOWN`, never "not available". Logs carry sanitized diagnostics: capture a fixture, update the mapper and `docs/09` |
| `/health/ready` reports `database: failed` | PostgreSQL unreachable | New searches fail with `503 SERVICE_UNAVAILABLE`; nothing is reported as saved. Restore the DB |
| Searches stuck in `RUNNING` | Process died | Reaped automatically after the grace period (§3) |

## 9. Before public launch (doc 06 §8)

Still open: RailKit written confirmation of commercial use, display, caching/storage and
redistribution rights; live contract verification (`make test-live`, docs/09 §5); user
authentication and per-user quotas; privacy policy and terms; security review and load test
with real provider latency.
