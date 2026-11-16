# RailRoute Optimizer - Project Instructions

## Project Overview
Commercial railway ticket availability optimization platform.

## Technology Stack
- Frontend: Next.js + TypeScript
- Backend: Python + FastAPI
- Railway provider: RailKit REST API
- Database: PostgreSQL
- Cache: Redis
- ORM: SQLAlchemy
- Migrations: Alembic
- Testing: Pytest, Vitest, Playwright
- Infrastructure: Docker Compose

## Finalized Business Decisions

1. Users select their preferred travel classes.
2. Quotas: General (GN) by default; Tatkal (TQ) selectable (2026-11-15, docs/08 D-20…D-26).
   TQ is queried only once its booking window (train origin date − 1 day, 10:00 AC /
   11:00 non-AC IST) is open. Premium Tatkal (PT) is not offered: RailKit rejects it.
3. All segments must belong to the same train.
4. Maximum 4 ticket segments per journey.
5. Passenger count is not required as user input.
6. Availability is checked for an individual ticket.
7. Support CNF, AVL, RAC, WL and unavailable states.
8. Preserve RailKit prediction and prediction percentage.
9. Actual availability and predicted confirmation must
   always remain separate.
10. Prediction can be used as a secondary ranking factor.
11. No direct ticket booking in MVP.

## Architecture Rules

- Use a modular monolithic backend.
- Keep railway provider integration independent.
- Never call RailKit directly from optimization logic.
- Use provider adapters.
- Keep API routes thin.
- Business logic belongs in services.
- Use asynchronous HTTP requests.
- Validate external API responses.
- Preserve raw provider responses where appropriate.
- Use PostgreSQL for persistent data.
- Use Redis for caching and coordination.

## Optimization Rules

- Model train stops as ordered graph nodes.
- Only allow forward-moving segments.
- Build a Directed Acyclic Graph (DAG).
- Generate valid paths from source to destination.
- Never exceed 4 segments.
- Every segment must belong to the same train,
  journey, travel class and quota (quotas are separate search spaces).
- Rank using actual availability first.
- Use provider prediction as a secondary ranking factor.
- Minimize the number of separate tickets.
- Never invent availability or prediction values.
- Share the budget fairly: every combination's direct ticket before any deeper level, equal shares
  within a level (docs/08 D-27). The search budget counts provider attempts, retries included (D-28).

## Engineering Standards

- Write clean, modular, maintainable code.
- Use type hints.
- Add unit tests for business logic.
- Add integration tests for provider adapters.
- Add API tests.
- Handle API failures gracefully.
- Never hardcode API credentials.
- Never expose RailKit credentials to the frontend.
- Use environment variables for secrets.
- Document significant architectural decisions.

## Development Workflow

1. Read relevant technical documentation.
2. Create an implementation plan.
3. Identify files to be created or modified.
4. Implement one milestone at a time.
5. Run automated tests.
6. Fix failures before proceeding.
7. Update documentation.
8. Report completed work and outstanding issues.

Never claim that an integration works without
a successful test or verified evidence.

## Repository Map and Commands

- `backend/` — FastAPI app (`app/`), Alembic (`migrations/`), tests (`tests/`). Python via `uv`.
  - Pure layers: `app/domain/` (stdlib only) and `app/optimization/` (domain only). Enforced by
    `tests/architecture/test_import_boundaries.py`.
  - RailKit code lives only in `app/integrations/railkit/`; it is wired in `app/providers/factory.py`.
  - Composition root: `app/container.py`. App factory: `app/main.py` (import-safe);
    server entrypoint: `app/asgi.py`.
- `frontend/web/` — Next.js 16 with Cache Components. Read `frontend/web/AGENTS.md` and the
  bundled docs in `node_modules/next/dist/docs/` before changing framework-level code. Data
  components that use TanStack Query, `useSearchParams` or the current time must sit inside
  `<Suspense>`. The browser calls the backend only through the same-origin proxy
  `app/api/v1/[...path]/route.ts`.
- Docker/local parity: a new `Settings` field must also be listed (without a value) in the
  `compose.yaml` backend `environment:` and documented in `.env.example`
  (`tests/unit/core/test_compose_parity.py`).
- Decisions and open provider questions: `docs/08_IMPLEMENTATION_PLAN.md`,
  `docs/09_RAILKIT_CONTRACT_VERIFICATION.md`.

Commands (from the repo root): `make check` (lint + types + tests, no infrastructure),
`make test-integration` (needs `TEST_DATABASE_URL` / `TEST_REDIS_URL`), `make test-e2e`
(Playwright; on this machine export
`LD_LIBRARY_PATH=$HOME/.cache/railroute/chromium-libs/root/usr/lib/x86_64-linux-gnu` first),
`make test-live` (spends real RailKit quota — only when explicitly asked).
Operations, deployment and incident handling: `docs/10_OPERATIONS_RUNBOOK.md`.

Local note: this machine also runs native PostgreSQL (5432) and Redis (6379); the Compose
services are published on `POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` instead (e.g. 55432 / 56379).
