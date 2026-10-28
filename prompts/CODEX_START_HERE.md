# Implementation Handoff

Read AGENTS.md, README.md, SPEC.md, CONSTRAINTS.md, docs/PRD.md, docs/ARCHITECTURE.md and docs/DECISIONS.md. Read the feature/domain contracts relevant to the selected task, including API.md and DATA_MODEL.md before schema/API work.

This repository is a requirements baseline. Do not start the full build unless the owner requests implementation. When implementation is authorized, select one small task from tasks/plan.md, state dependencies, implement it and verify appropriate checks.

Use PostgreSQL as source of truth, React+Vite/FastAPI, Alembic migrations and a separate idempotent development seed command. Follow docs/SEED_DATA.md for Paychex/OnTrac and administrator/user bootstrap; never copy example shipment/contact data into seeds.

Preserve supplied API paths/messages and current data mappings. Reference files preserve original examples and may contain obsolete fields; active contracts govern. Do not run the MySQL-shaped legacy schema against PostgreSQL.

Business decisions are recorded; database keys/indexes, receipt metadata and API DTO wiring are engineering work. Ask only when a new unresolved business behavior actually affects the selected task. Do not reopen completed decisions or infer approval to provision AWS, Elasticsearch, Pusher or outbound carrier services.

Report changes, actual validation and remaining limitations. A passing documentation check is not a passing application test.
