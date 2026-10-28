# Product Requirements

## Purpose
Give shippers one dashboard to follow every package across the carriers handling their deliveries. A shipment represents one package. Company data and user permissions remain isolated throughout ingestion, display, notifications and export.

## Actors
| Actor | Responsibility |
|---|---|
| Shipper user | View own company's packages, metrics, details, Search and exports |
| Shipper administrator | Same access, plus manual area create/edit/delete/restore |
| Shipper file source | Submit manifests under its registered source identity |
| Carrier integration | Submit tracking updates for assigned accounts/shipments |
| Background workers | Normalize/validate inputs and apply replay-safe effects |

## MVP capabilities
1. Login using email, password and company slug.
2. Create packages from Paychex manifests or the shipment creation API.
3. Reuse matching tenant-owned customer addresses without mutating historical addresses.
4. Receive OnTrac CSV/webhook events, repeated attempts, returns, signer/POD and optional deadline/route updates.
5. Display due-today global/area metrics and Exceptions on My Day.
6. Display Tracking with date/account/status/area/exception filters, counts and pagination.
7. Search by an explicitly selected identifier, opening one matching detail or a selection table.
8. Display shipment detail, original addresses, repeated history and latest POD.
9. Manage company-shared areas with administrator-only manual controls.
10. Queue full-filter CSV exports and notify the requesting dashboard over SSE when ready.
11. Bootstrap catalogs, companies and Paychex development users through an editable repeatable seed command.

## Ownership and identity
company.company_type distinguishes carrier=1 and shipper=2. users.role_id distinguishes administrator and user. Shipments store shipper_company_id and carrier_company_id; reference input maps to shipper_ref and is unique within the shipper. shipment_number is a mutable carrier identifier and may be generated at initial API creation.

## Operational behavior
Process valid CSV rows despite rejected rows. Store rejected/unmatched diagnostics in PostgreSQL. Unknown carrier event codes are ignored. Exact canonical event duplicates produce no side effects. Determine current outcomes by event time with receipt-order ties; deadlines and permitted ordinary fields use the approved receipt-order rules.

Addresses are immutable after creation. Areas organize packages but never determine whether a package exists. Deleted areas remain hidden while retaining links; Void applies to deleted shipments, remains visible/countable and is excluded from OTP.

## Development bootstrap
Seed Paychex and OnTrac, shared role/action catalogs, and Paychex administrator/user accounts. Generate initial passwords at seed runtime, store password hashes and preserve existing accounts on reruns. Do not seed sample packages, real mappings, integration keys or contact data. See [SEED_DATA.md](SEED_DATA.md).

## Later phases
| Work | Status |
|---|---|
| Carrier-facing dashboard | Phase 2 planned; company-scoped carrier data |
| Outbound shipment-submission worker | Planned; sends shipment_number and reference |
| Elasticsearch | Deferred; PostgreSQL is the initial source and read model |
| Detail map and favorite/star | Deferred |
| Real AWS uploads and production bucket configuration | Deferred |
| Additional carrier/shipper adapters | Add through explicit source contracts |

## Success criteria
A shipper can create/import packages, follow accepted carrier history, distinguish incomplete POD from completed delivery, inspect accurate metrics, find packages and export all filtered results. No company can access another company's packages or generated artifacts. Retries and concurrent processing preserve package/event identity and committed valid rows.
