# Logistics Tracking Platform

Requirements baseline 1.0 with P1 scaffolding, P2 migrations/development seeding, P3 shipper login/session management, P4 creation/address/account/area persistence, P5 Tracking/Search/detail APIs, P6 Tracking/Search/detail/area UI, P7 durable Paychex manifest intake, P8 authenticated OnTrac carrier events, P9 POD preparation/independent storage retries, P10 My Day statistics/charts, P11 queued CSV export/SSE recovery, and P12 end-to-end/recovery verification with measured PostgreSQL baseline. React/Vite TypeScript, FastAPI and Docker Compose PostgreSQL/Redis are runnable; shipment creation, area and query APIs are available. The shipper UI now supports My Day, Tracking, Search, detail and administrator area controls; the optional ingestion worker supports finalized Paychex CSV imports with durable row recovery and archives. OnTrac webhooks and CSV events now update history, status and authorized fields; JPEG/PNG POD input is validated/resized and queued independently, with a development dummy storage adapter. Contracts are in [QUERY_IMPLEMENTATION.md](docs/QUERY_IMPLEMENTATION.md) and [UI_IMPLEMENTATION.md](docs/UI_IMPLEMENTATION.md). See [file intake details](docs/FILE_INGESTION_IMPLEMENTATION.md) and [local startup and checks](docs/DEVELOPMENT.md).

## Product
A multi-tenant shipment tracking dashboard for shippers. One shipment is one package. Each shipper sees its own packages across all carriers handling them. The first adapters support Paychex manifests and OnTrac tracking updates.

The MVP includes login, My Day, Tracking, identifier Search, shipment detail, administrator-managed areas, CSV ingestion, carrier webhooks, POD images and asynchronous CSV exports with SSE notifications.

## Documentation map
| Document | Purpose |
|---|---|
| [SPEC.md](SPEC.md) | Scope, stack, delivery boundaries and acceptance gates |
| [Product requirements](docs/PRD.md) | Actors, workflows and business outcomes |
| [Architecture](docs/ARCHITECTURE.md) | Components and data flow |
| [Data model](docs/DATA_MODEL.md) | Target entities, ownership and constraints |
| [API contract](docs/API.md) | Supplied routes, request mappings and response behavior |
| [Feature specifications](docs/features/002-tracking.md) | Page-level behavior; see the feature index in SPEC.md |
| [Development](docs/DEVELOPMENT.md) | Local environment and implementation tooling |
| [Seed data](docs/SEED_DATA.md) | Repeatable development companies, catalogs and users |
| [Implementation plan](tasks/plan.md) | Small dependency-ordered delivery tasks |
| [Requirement-writing guide](docs/REQUIREMENTS_TEMPLATE.md) | Reusable template and examples |
| [Decision history](docs/DECISIONS.md) | Retained interview decisions and rationale |

Business rules are owned by their domain contracts: [identity](docs/TENANCY_AND_IDENTITY.md), [accounts](docs/ACCOUNT_MAPPING.md), [creation](docs/SHIPMENT_CREATION.md), [events](docs/EVENT_MODEL.md), [status/metrics](docs/STATUS_RULES.md), [deadlines](docs/DEADLINE_RULES.md), [time](docs/TIME_RULES.md), [files](docs/FILE_INGESTION.md), [POD](docs/POD_STORAGE.md) and [security](docs/SECURITY.md).

## Baseline conventions
- Requirements describe the intended system. Items labeled **Engineering choice** or **Recommendation** are not additional business decisions.
- DECISIONS.md retains the chronological discussion. Reference files retain their original content and may differ from the current contracts; active specs govern implementation.
- The MySQL-shaped [legacy schema](docs/reference/legacy-schema-source.md) is reference material, not executable PostgreSQL DDL or a live migration source. Start with new data.
- Preserve supplied API spelling and exact messages. Never use shipment/contact samples as real seed data.
- Do not begin the full application build as part of documentation preparation. Work in small reviewed slices using AGENTS.md.

## Deferred work
Elasticsearch is deferred. Carrier dashboards are planned for phase 2. Outbound carrier submission, map/favorite features, actual AWS setup and additional adapters are outside the initial implementation scope.

P10 delivers due-today global/exception/active-area statistics and accessible charts. See [dashboard implementation](docs/DASHBOARD_IMPLEMENTATION.md). P11 adds real local CSV downloads and authenticated SSE readiness recovery; see [export implementation](docs/EXPORT_IMPLEMENTATION.md). P12 verifies real browser flows, isolated outages and a synthetic PostgreSQL performance baseline; see [verification and operations](docs/P12_VERIFICATION.md). Production capacity/storage configuration remains separate.
