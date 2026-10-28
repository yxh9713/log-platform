# Project Instructions

Implement a multi-tenant shipment tracking system. One shipment means one package. Read README.md, SPEC.md, CONSTRAINTS.md, docs/DECISIONS.md, the relevant feature specification and its domain/API contracts before coding.

## Working rules
- The clean baseline describes current requirements; DECISIONS.md retains history. Read current decision statuses rather than reopening completed business questions.
- Treat genuinely unanswered business rules as questions; never silently implement them. Distinguish requirements, engineering choices and recommendations.
- Preserve approved paths and exact response text, including POST /v1/webhook/{integrationId} with raw ID and X-API-Key.
- PostgreSQL is the target. Never execute docs/reference/legacy-schema-source.md as PostgreSQL DDL or reproduce its invalid indexes/keys.
- Work in small dependency-ordered slices; synchronize schemas, API DTOs, frontend and tests. Do not build the whole product during baseline preparation.
- Reference shipment/contact samples are not real tenant seed data. Only the companies, catalogs and development users specified in docs/SEED_DATA.md are authorized seed content.

## Security and ownership
- Authenticate token and verified company membership. MVP dashboard is shipper-only: shipments.shipper_company_id=user.company_id across all its carriers.
- company.company_type is 1 carrier/2 shipper; users.role_id references user_role administrator/user. Manual area mutations require a company administrator.
- Carrier integrations use integrations.apikey hash verification for the routed integration; raw ID and payload sign are not authentication. Resolve carrier/account through trusted account_mapping before shipment matching.
- Incoming reference maps to shipments.shipper_ref, unique with shipper_company_id. Preserve string identifiers and reference priority; carrier shipment numbers may repeat under different references.
- Never log real credentials or base64 POD. The development seed command may generate initial passwords at runtime because the owner explicitly requested it; store only password hashes and do not commit generated passwords.

## Data integrity
- Use PostgreSQL as canonical state; Redis is derived/broker support. Elasticsearch is deferred.
- Enforce unique shipment/action/event_time; exact duplicate events have no business effects. Select events by event_time and receipt tie order, not worker completion.
- Preserve immutable shipment addresses and tenant-scoped customer reuse. Missing/empty/null update fields preserve values.
- Unknown event codes are ignored. Unmatched shipments create PostgreSQL ingestion errors, not shipments/events or delayed automatic event retries.
- Valid CSV rows survive rejected rows; partial files go to failed with completed_with_errors. Follow docs/FILE_INGESTION.md for finalization/dedupe/archive behavior.
- Follow docs/POD_STORAGE.md for image validation/resize and independent pending-image retries. Real AWS setup remains deferred.

## Definition of done
Run checks appropriate to the slice: happy path, errors, tenant/role isolation, retry/dedupe, migration/API consistency, formatting/type checking. Report actual results and limitations. Documentation tests are not application tests; no credentials or external services are provisioned by writing requirements.
