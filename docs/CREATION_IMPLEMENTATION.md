# P4 persistence and creation interfaces

P4 implements the storage/services required before shipment queries and ingestion. It adds POST /v1/shipments and the already approved area CRUD endpoints. It does not add Tracking/Search/detail UI, area statistics, carrier receipt, CSV processing, POD or export behavior. D49 records the owner's explicit existing-reference API decision.

## Creation interface
POST /v1/shipments requires a verified active shipper session (cookie or bearer). Cookie mutations use the P3 Origin/header guards. The body follows SHIPMENT_CREATION.md: required string reference, required account_number and carrier_id service selector, and required from_address/to_address. Optional shipment_number, reference_two, service_name, package.weight and due_time are supported. signature_required/sort_code are accepted but have no behavior/persistence. Other unknown fields (including client company IDs, route, contact and address_three) are rejected.

Strings are trimmed; identifiers and ZIP values remain strings with original case/leading zeros. New optional empty/null values become NULL. Input bounds are engineering choices: names/lines/identifiers 255 characters, city 128, state 64, ZIP 32, phone 64, email 320, address note 4000 and service selector 64. Creation bodies are capped at 64 KiB before JSON parsing. Weight uses Decimal/ROUND_HALF_UP, two places, nonnegative/finite, rounded maximum 999.99. Missing package/weight is NULL, not zero; no unit conversion occurs.

On first creation return 201. A valid retry for the same verified shipper/reference returns 200 and the original package unchanged, including when nonempty replacement values are supplied (D49). Request validation still applies. Account/service values must either match the original stored creation selector/account, or be a valid current mapping within that shipper; they never reassign the existing package. Old valid retry assignments survive mapping edits. A malformed explicit retry deadline is rejected, not applied. Source import/carrier corrections are separate future ingestion services.

The typed response contains id, reference, shipment_number, carrier_company_id, account_number, reference_two, service_name, sender_id, recipient_id, weight, due_time, due_date and route. New stable/internal IDs are decimal strings; route retains the approved nullable integer area ID. Weight is serialized as a decimal string or NULL. due_time is ISO 8601 with the recipient's actual offset when known, otherwise +00:00. due_date is always the persisted UTC date. No full address/contact data is echoed in this creation acknowledgement. Success responses use Cache-Control: no-store. This is a creation acknowledgement, not the P5 detail/list DTO.

Required account failure is exactly HTTP 400 {"message":"account is required"}. Missing/invalid/mismatched service/account and invalid supplied deadline strings are 400 with descriptive message objects. Other body validation is 422 {"message":"Invalid shipment request"}; body limits return 413. Authentication/CSRF errors use P3's 401/403. Database/configuration failures return sanitized 503 responses. OpenAPI declares the input, response models and error bodies. No public account-management or address-validation API is added.

## Transactions and defaults
A PostgreSQL transaction lock per shipper serializes creation/assignment/area mutations, while unique keys protect other writers. Validate input/assignment before accepting business effects; any invalid deadline/generator/database error rolls back customers, reservations, shipment and Created event together. Invalid authenticated creation requests record a separate PostgreSQL ingestion_errors row with tenant/user/source, reason code, bounded account/reference and database time. Addresses, passwords and raw payloads are not stored in those diagnostics or logs. Transport-size/unauthenticated rejections have no trusted business receipt. Diagnostics outages return 503 rather than claiming a durable error was recorded. Shared service callers outside HTTP must handle their own source-specific diagnostics; file receipt/outcome storage remains P7.

New shipments persist immutable tenant/reference, sender/recipient pointers, original carrier/account and creation_service (the original API service selector). Defaults: route/weight/order_date/deliver_time/pod_name/notes/deleted_at NULL; order_date is never invented from processing time. PostgreSQL transaction time anchors created_at and exactly one Created event. Missing due_time gets next UTC calendar weekday at 17:00; supplied weekend deadlines are not shifted. Replays never regenerate a number, deadline or Created event.

API due_time formats are ISO YYYY-MM-DD (17:00 UTC) or ISO date-time with an optional explicit offset. Naive date-times use the recipient's tenant-scoped validated timezone, falling back to UTC when absent. Invalid nonempty zones and ambiguous/nonexistent local times reject instead of guessing; explicit offsets preserve their instant. Epochs and bare clock strings are not inferred. Provider-specific source formats will be defined by their adapters.

## Physical design
Revision 0003_creation_core adds nine tables and a receipt sequence:

- customers_validated: tenant-scoped validation linkage, optional timezone/coordinates and metadata; no validation worker/external service is provisioned.
- customers: immutable original address identity, optional metadata, tenant/validation FKs and a six-field tenant reuse key with PostgreSQL NULLS NOT DISTINCT for address_two. Reuse never overwrites existing note/phone/email.
- carrier_accounts: retained carrier/account-to-shipper ownership, unique carrier/account; different carriers may reuse the same account spelling.
- account_mapping: unique current shipper/service assignment, linked to retained account ownership. Multiple services for the same owner/account are valid.
- area: normalized company/name uniqueness including deleted rows, soft deletion and timestamps.
- generated_shipment_numbers: permanent generated-number reservations; no blanket shipment_number uniqueness.
- shipments: canonical package/assignment/address/deadline fields, unique shipper/reference, tenant-composite customer/route FKs and UTC deadline/date consistency.
- shipment_events: initial Created history with exact shipment/action/event_time uniqueness and event/receipt order index.
- ingestion_errors: minimal scoped creation diagnostics, allowing missing shipment ID.

Database triggers reject original customer address and shipment identity/address/assignment changes. Updating validation linkage remains possible within the same tenant; cross-company validation links are rejected. Ordinary authorized event/number/deadline/route fields remain available for future ingestion. A shared advisory lock coordinates all shipment-number writes and generation, including trusted SQL/future carrier updates. Generation tries at most ten cryptographically random 15-character A–Z/0–9 candidates, checking existing source numbers and permanent generated reservations. Later supplied duplicate numbers remain valid under different references. The global number lock is a correctness-first local baseline; throughput must be measured before production.

The event receipt sequence currently allocates the initial synchronous Created event's order. P8 must allocate/persist source acceptance order before asynchronous processing and must not treat worker completion as receipt order. P4 does not implement current-outcome reduction or ingestion retries.

## Mapping configuration
AccountMappingService.configure is a trusted operator helper, not a dashboard route. It validates active shipper/carrier company types and preserves old carrier_accounts rows when replacing a current service mapping. resolve_shipper can therefore authorize historical carrier/account ownership after edits. Database uniqueness rejects conflicting owners while permitting multi-service reuse. No mapping/account data is seeded, and no sample account is installed.

To configure real local assignments, use an explicit backend Python session with the actual owner-provided company IDs, service and account, then call AccountMappingService(create_database_engine(DatabaseSettings())).configure(...). The arguments are shipper_id, carrier_id (actual carrier company ID for this trusted helper), service (the create API's carrier_id selector), account. Do not copy reference account/service examples as assignments.

## Areas
All shipper members read GET /v1/areas; it returns active id/name options alphabetically. Administrators alone POST /v1/area, PUT /v1/area/{id} and DELETE /v1/area/{id}; the service independently rechecks current DB membership/role, so a forged/stale Principal role cannot bypass it.

Names trim/lowercase, permit letters/numbers/spaces/hyphens/underscores and cap at 64 characters. New POST is 201; manual deleted-name restore is 200 with the original id/name. Active duplicate is 400 {"message":"sfo already exist"}, substituting the normalized name. Duplicate PUT is a 200 no-op returning the original target's actual id/name. Deleted PUT is rejected until manual restore. DELETE/repeated DELETE is 200 {"message":"Area deleted"}; existing route links remain intact. Wrong-tenant IDs are 404. Invalid names/path IDs are 422 with a sanitized message. No area-statistics or carrier area-assignment endpoint is included; those require their later query/ingestion slices.

## Verification boundary
P4 tests use only disposable PostgreSQL databases with synthetic packages/accounts/addresses. The local development migration creates schema but no package/contact/account/area seed records. Frontend code remains P3's login/layout; existing Vitest/jsdom tests and build are regression checks, not a Playwright/E2E claim. Current SQL/schema/service/API tests cover concurrent reference/address reuse, generated-number races, account conflicts/history, immutable fields, tenant FKs, weight/deadline boundaries, diagnostics rollback and exact area responses.
