# RailRoute Optimizer — Engineering Documentation Pack

(Moved from the repository root; the root `README.md` is now the developer guide.)

Version: 1.0 (MVP baseline)  
Product: Commercial railway availability discovery and same-train segment optimizer  
Primary market: India  
Timezone: Asia/Kolkata for railway journey dates and displayed timestamps

## Contents

- `01_PRODUCT_AND_SRD.md` — product definition, scope, users, requirements and acceptance criteria.
- `02_ARCHITECTURE.md` — component architecture, boundaries, data flow, deployment and security.
- `03_RAILWAY_DOMAIN_AND_RULES.md` — train, station, segment, availability and prediction semantics.
- `04_OPTIMIZATION_ENGINE.md` — graph model, path algorithm, ranking and query planning.
- `05_API_SPECIFICATION.md` — internal REST API contracts.
- `06_DATA_MODEL_AND_OPERATIONS.md` — PostgreSQL model, caching, observability, testing and operations.
- `07_RAILKIT_INTEGRATION.md` — provider adapter contract and RailKit integration notes.
- `08_IMPLEMENTATION_PLAN.md` — milestones, decisions taken where this pack was silent, conflicts found.
- `09_RAILKIT_CONTRACT_VERIFICATION.md` — RailKit contract evidence, open questions, live-check procedure.
- `10_OPERATIONS_RUNBOOK.md` — deployment, configuration, incident handling (added in Milestone 7).

The original pack also referenced `agent/AI_CODING_AGENT_MASTER_PROMPT.md` and
`agent/IMPLEMENTATION_CHECKLIST.md`; those files were not part of the repository (the master prompt
was supplied directly to the implementing agent).

## Final decisions (binding)

| Decision | MVP value |
|---|---|
| Frontend | Next.js + TypeScript |
| Backend | Python + FastAPI |
| Railway data | RailKit REST API |
| Database | PostgreSQL |
| Cache / coordination | Redis |
| Client platform | Responsive web/PWA first; API and UI architecture mobile-ready |
| Train scope | One train for every segment in a recommendation |
| Classes | User selects one or more supported classes |
| Quota | General (`GN`) only |
| Maximum segments | 4 tickets per recommendation |
| Passenger count | Not collected; each segment is checked as a single-ticket availability query |
| Availability | Current provider status is mandatory |
| Prediction | Preserve and use RailKit prediction when returned; never conflate it with current status |
| ML | No custom model in MVP |
| Booking | No automated booking; outbound links / booking guidance only |
| Probability | No independently generated probability in MVP; provider prediction only |

## Important implementation rule

RailKit is an external provider, not the domain model. Its API response must be adapted into our stable internal schema. The graph and ranking engine must not import RailKit-specific modules.

## Source-of-truth and verification

RailKit API contracts can change. Before implementation is considered integration-complete, the developer must verify the current endpoint path, date format, authentication header, response schema, rate limits, plan limits, caching policy, commercial redistribution rights and permitted query volume against the live RailKit documentation/account.

The documentation referenced during preparation:
- https://railkit.in/docs
- https://railkit.in/docs/seat-availability
- https://railkit.in/docs/train-search

The published RailKit documentation currently describes:
- Train search: `GET /api/v1/trains/between/:fromStnCode/:toStnCode?date=DD-MM-YYYY`
- Train info: `GET /api/v1/trains/:trainNumber/info`
- Availability: `GET /api/v1/seats/:trainNo/:fromStnCode/:toStnCode/:date/:coach/:quota`
- Fare lookup: `GET /api/v1/fare/:trainNo/:date/:fromStation/:toStation/:class/:quota`
- Station search: `GET /api/v1/stations/search?name=...`
- API-key authentication; keep the key on the backend.

Do not hardcode assumptions based on sample payloads. Build contract tests and retain sanitized raw payloads in development/test fixtures.
