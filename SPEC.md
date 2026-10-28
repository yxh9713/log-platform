# System Specification

Requirements baseline 1.0. Business requirements are established. P1 scaffolding, P2 identity/catalog migrations/development seeding, P3 shipper login/session management, P4 creation/address/account/area persistence, P5 Tracking/Search/detail APIs, P6 Tracking/Search/detail/area UI, P7 file lifecycle/Paychex manifest intake, P8 OnTrac webhook/CSV event ingestion, P9 POD processing/storage retries, P10 My Day statistics/charts and P11 queued CSV exports/SSE are implemented. P12 supplies real browser/integration/recovery verification, read-only diagnostics and a measured local PostgreSQL baseline; production deployment configuration remains separate. See tasks/plan.md for verification results.

## Scope
The system provides a shipper-only MVP dashboard for tracking packages across carriers. One package equals one shipment. Initial integration adapters are Paychex manifests and OnTrac carrier CSV/webhooks. All data access is tenant-scoped.

| Included | Deferred |
|---|---|
| Login and administrator/user roles | Carrier dashboard, planned phase 2 |
| My Day, Tracking, typed identifier Search, shipment detail | Detail map and favorite/star |
| Company-shared areas and carrier route assignment | Area/account-management administration beyond specified workflows |
| Manifest/API creation and carrier event ingestion | Outbound carrier shipment-submission worker |
| Repeated event history, deterministic status and OTP | Elasticsearch/search-index infrastructure |
| POD validation, resize, history and dummy storage adapter | Real AWS SDK/bucket/credential setup |
| Queued CSV exports and SSE readiness notification | General-purpose/fuzzy Search |
| Alembic migrations and development seed command | Live MySQL sync or legacy shipment backfill |

## Technology
| Component | Target |
|---|---|
| Frontend | React + Vite; TypeScript engineering baseline |
| API | Python/FastAPI |
| Source of truth | PostgreSQL, UTC database/session reporting |
| Jobs/cache/live distribution | Redis support; queue framework selected during implementation |
| Schema migrations | Alembic |
| Local orchestration | Docker Compose |
| Notifications | Authenticated SSE |
| Development files | Local sftp directory and storage adapters |

Pinned versions, lockfiles and runnable commands are documented in docs/DEVELOPMENT.md. Verification evidence is scoped to completed slices in tasks/plan.md.

## Feature index
- [Login](docs/features/000-login.md)
- [My Day](docs/features/001-my-day.md)
- [Tracking](docs/features/002-tracking.md)
- [Search](docs/features/003-search.md)
- [Areas](docs/features/004-areas.md)
- [Shipment detail](docs/features/005-shipment-detail.md)
- [CSV export](docs/features/006-shipment-export.md)

## Dependencies
Tenant/company/role authentication precedes protected queries. Schema and seed infrastructure precede the login slice. Creation and account assignment precede event ingestion. Canonical event/status/deadline rules precede metrics. Export reuses list predicates; notifications rely on durable job state.

## Acceptance gates
Each slice must include aligned schema/API/frontend contracts, appropriate tests, formatting/type checking and documented results. Required coverage includes tenant isolation, role checks, invalid inputs, repeated files/events, out-of-order updates, partial CSV success and infrastructure retry behavior.

Use the [implementation plan](tasks/plan.md), [engineering constraints](CONSTRAINTS.md) and [project instructions](AGENTS.md). Decision history is retained in [DECISIONS.md](docs/DECISIONS.md); it is not a second mutable API contract.
