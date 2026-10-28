# Target Data Model

## Conventions
PostgreSQL is canonical. Company/session reporting timezone is UTC. Preserve identifiers/ZIP as strings; use aware instants and decimal weight. The supplied MySQL/Laravel schema is reference, not executable DDL or live import data.

Use the explicitly approved table names below; do not pluralize company, area or user_role merely because integrations/shipments/users are plural. Exact ID/FK/index implementation is engineering design.

## Core entities
| Table | Required logical fields and relationships |
|---|---|
| company | id, name, slug, active, company_type (1 carrier, 2 shipper) |
| user_role | id, name; shared administrator/user catalog |
| users | id, company_id, role_id, email, password (hash only), active state and timestamps |
| auth_sessions | P3: token_hash digest PK, user_id/company_id composite membership FK, created_at/expires_at aware instants |
| customers | id, company_id, company (input name), address_one, address_two, city, state, zip, note, phone, email, validated_id, timestamps |
| customers_validated | id, normalized validation metadata/coordinates, timezone VARCHAR |
| account_mapping | id, shipper_company_id, carrier_company_id, service VARCHAR(64), account_id |
| integrations | id, company_id (carrier), apikey verifier, adapter/activation metadata and timestamps |
| area | id, company_id (shipper), name, deleted_at, created_at, updated_at |
| shipments | id, shipper_company_id, carrier_company_id, account_id, shipment_number, shipper_ref, shipper_ref2, service_type, sender_id, recipient_id, route, weight, order_date, due_date, due_time, deliver_time, pod_name, notes, deleted_at, timestamps |
| shipment_actions | id, action VARCHAR(64); seven shared catalog labels |
| shipment_events | id, action_id, shipment_id, event_time, created_at; durable receipt association as needed |
| shipment_images | id, shipment_id, accepted-event linkage, url, readiness/retry metadata, size/dimensions and timestamps as needed |

order_date reflects a supplied source order date when available; do not substitute creation/event time for a missing source value in exports. Names such as source order timestamp storage and DTO typing are implementation mapping details. Do not add contact/address_three fields to the current address contract.

## Required invariants
- Unique company slug and role/action catalog names; user identity is email within company.
- Unique(shipper_company_id, shipper_ref). shipment_number has no blanket hard uniqueness rule that rejects permitted source-number conflicts; generated numbers need safe unique reservation.
- Unique(shipment_id, action_id, event_time), never one event per action/shipment. Retain repeated history.
- Address reuse key is tenant plus trimmed name/address_one/address_two/city/state/zip, with NULL address_two equality. Existing original addresses/pointers remain immutable.
- Required address fields are nonempty name/address_one/city/state/zip; optional blanks→NULL at creation. Name maps to customers.company.
- Weight nullable NUMERIC(5,2), nonnegative, two-decimal rounding, maximum 999.99; no unit inference.
- Required normalized/defaulted due_time/due_date on creation; one final actual delivery time. shipment_status/tracking_events are not target tables.
- Route is nullable integer area.id, constrained to the shipment's shipper company. Names unique per company including deleted rows, trimmed/lowercase/max64 with approved characters.
- One current shipper/service mapping gives one carrier/account. Carrier/account identifies one distinct shipper, while multiple service rows for that same shipper/account are valid.
- Preserve image history and idempotent pending image retry; legacy UNIQUE(shipment_id,pod_type) must not prevent multi-event POD.

## Durable processing records
Implement PostgreSQL import runs, receipts/row outcomes, ingestion errors, export jobs and pending image work as required by their contracts. Error records can lack shipment_id; never manufacture a placeholder shipment to satisfy a relationship.

Store trusted source/tenant/requester scope, raw/provenance references, normalized effective filters, state/counters and diagnostics. Source receipts are not canonical shipment_events. Physical names, indexes, transaction guards and outbox/queue associations are engineering work.

**Recommendation:** ingestion_source(id, company_id, source_type, poll_interval_seconds, enabled) for independently configurable file polling. Keep it separate from webhook authentication and account assignment.

## Index and migration design
Use reference/event uniqueness, tenant-first filter paths, shipment history order and address matching indexes as starting candidates. Verify PostgreSQL query plans with representative synthetic data. Never propose a cross-table index or raw-event aggregate that multiplies shipments.

Do not copy the legacy unique password index, inconsistent primary-key spelling, missing-field indexes or MySQL type syntax. Alembic creates the new schema; development seed is a separate idempotent command in SEED_DATA.md. No legacy shipment conversion/backfill is required.

## Implemented P2 boundary
Revision `0001_identity_catalogs` creates only company, user_role, users and shipment_actions. IDs are PostgreSQL BIGINT identities; company_type is constrained to 1/2; slug/catalog names are unique; user email identity is unique within company. Names/emails have nonempty normalized-value checks, password is nonempty TEXT with no unique index, membership/role foreign keys restrict dangling/deleted parents, and user timestamps are timezone-aware. Application writes in later slices must explicitly maintain updated_at; no update trigger is installed. The migration inserts no rows. SQLAlchemy Core metadata in `backend/app/db/schema.py` is checked against migrated PostgreSQL by tests and `alembic check`. Other target entities in this document remain future work.

## Implemented P3 boundary
Revision `0002_auth_sessions` adds durable sessions and an explicit unique (users.id, users.company_id) key for the composite session membership FK. Session rows store digests only, enforce nonempty lowercase 64-character hexadecimal hashes and expires_at > created_at, and index expiry and membership. Deleting a user cascades its sessions; company membership cannot be changed underneath existing linked sessions. Logout deletes a session; expired sessions are ignored, with retention cleanup left to deployment configuration. No tenant shipment or area tables are added.

## Implemented P4 boundary
Revision 0003_creation_core adds customers_validated/customers, carrier_accounts/account_mapping, area, generated_shipment_numbers, shipments, shipment_events and ingestion_errors. The validation table has company_id to enforce tenant-scoped validation linkage. shipments.creation_service is the original service selector; sender/recipient/route FKs include the shipper tenant. Customer reuse uses PostgreSQL NULLS NOT DISTINCT and address immutability triggers. Required UTC deadlines, exact event triples and reference uniqueness are database constraints. Retained account ownership and generated-number reservations support history/collision correctness without prohibiting repeated source shipment numbers. See CREATION_IMPLEMENTATION.md for physical choices, API DTOs and remaining ingestion/query boundaries.

## Implemented P7 boundary
Revision 0004_manifest_intake adds ingestion_source, ingestion_imports, ingestion_rows and shipment_field_receipts. Source-scoped content/arrival keys, stable logical row receipts, same-source duplicate links and linked source/import/row diagnostics support recovery. Checks constrain adapters, safe folders, states and counters; archive state is independent of business completion. Shared creation initializes field receipts without changing API DTOs. No rows or reference data are inserted by this migration. See FILE_INGESTION_IMPLEMENTATION.md.

## Implemented P8 boundary
Revision 0005_carrier_events adds integrations with SHA-256 API-key verifiers and carrier_receipts with immutable request digests, receipt order and outcomes. shipment_events retains source-time/zone provenance; ingestion_errors links carrier/integration/receipt and CSV rows retain accepted/duplicate/ignored outcome counters. Source adapter and field-receipt constraints now include OnTrac/route/signer. Existing event/reference/tenant constraints remain. No credentials, mappings or tenant data are inserted. See CARRIER_INGESTION_IMPLEMENTATION.md.

## Implemented P9 boundary
Revision 0006_pod_images adds shipment_images with event/tenant composite ownership FKs, unique accepted-event/object-key associations, measured sizes/dimensions/MIME/hash, prepared BYTEA and independent pending/retry_wait/ready/failed state. Supporting shipment/event composite unique keys precede image FKs; ingestion_errors can reference an image. Readiness constraints keep pending/failed URLs null and prepared data available until ready. No images or source records are seeded. See POD_IMPLEMENTATION.md.

## P11 export queue
Alembic 0007_exports adds export_jobs: UUID identity, verified company/requester composite FK, normalized JSONB filters with explicit effective dates, pending/retry_wait/ready/failed state, bounded attempts/next-attempt/reason, filename/size/row-count/SHA-256 ready metadata, timestamps and optional durable notification dismissal. Readiness checks prevent ready rows without complete artifact metadata. Indexes cover pending scans and requester recovery. No shipment/customer/catalog seed change is included; PostgreSQL owns durable state, while CSV bytes live under the local download adapter root. See EXPORT_IMPLEMENTATION.md.
