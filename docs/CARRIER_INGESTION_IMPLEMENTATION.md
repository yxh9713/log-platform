# P8 carrier events and ingress

P8 implements raw-ID OnTrac webhooks, OnTrac CSV intake and shared event/field/outcome transactions. Approved business contracts remain INGESTION.md, EVENT_MODEL.md, INTEGRATION_ADAPTERS.md, ACCOUNT_MAPPING.md, DEADLINE_RULES.md, TIME_RULES.md, STATUS_RULES.md and SECURITY.md. P9 now adds POD image validation/resize/storage retry and selected image URLs; see POD_IMPLEMENTATION.md. No new dashboard UI or external service is added.

## Schema and trusted setup

Revision `0005_carrier_events` adds `integrations` and `carrier_receipts`, event source-time/normalization-zone metadata and an indexed source-time lookup, carrier/integration/receipt diagnostics, CSV outcome columns/counters and expanded source/field constraints. Existing rows/users/passwords are preserved. Migration/seed create no integrations, API keys, source registrations, carrier accounts, mappings, shipments or sample contacts.

An operator provisions a high-entropy key and manually stores only its lowercase SHA-256 hex verifier in integrations.apikey. integrations.company_id must identify an active carrier company, adapter is ontrac and active must be true. IDs are ordinary PostgreSQL BIGINT identities. Do not encode/decode the URL ID. No key-management UI, plaintext-key table or provision command is added. Trusted carrier_accounts retained by AccountMappingService resolve historical ownership after future-only mapping edits.

## Webhook interface

`POST /v1/webhook/{integrationId}` requires exactly one X-API-Key header. User cookies/bearer tokens do not authorize carrier ingress. The service verifies the live routed integration/company and constant-time digest before reading JSON, then rechecks it transactionally after reading. Manual replacement, deactivation and cross-integration keys take effect without a cache. Invalid/missing keys or invalid/unknown raw IDs return exactly HTTP 401 `{"message":"Invalid API key"}` without ingestion receipts/errors/business effects.

**Engineering interface:** authenticated requests must be application/json objects with unique keys and valid JSON constants, with a streamed 7,000,000-byte ceiling. Malformed JSON/non-object/repeated keys return 400; non-JSON media type returns 415; oversized content returns 413. These transport failures precede business acceptance and do not persist raw bodies. SQL failures return a sanitized 503. Keys, raw JSON, notes/contact payloads and image data are never logged.

OpenAPI describes account/reference/event/time and optional shipment_number/sign/pod/notes/route/due_time. Known-event inputs require bounded string identifiers/account/time; identifiers remain exact after surrounding whitespace trimming. Extra webhook keys are rejected for known events, including attempts to choose a company or edit addresses. Notes max 4000, signer max 255, route max 64, time/deadline max 128 and identifiers max 255 characters. Empty/null optional updates preserve values.

The exact six CSV mappings are accepted; webhook additionally accepts Delivered. Case aliases are not inferred. A present, bounded unknown event code is ignored before matching/time/deadline/area/image validation, with no business effects. Account/reference/time remain required for known events; deadline-only messages are rejected. CSV timestamp and webhook time are event time; status/order are ignored.

Successful synchronous processing returns HTTP 200 after the PostgreSQL transaction commits:

```json
{"message":"Event accepted","outcome":"accepted","receipt_id":"UUID"}
```

Duplicates use message `Duplicate event ignored` / outcome duplicate; unknown codes use `Unknown event ignored` / outcome ignored. Each valid authenticated business attempt has a new receipt ID/order, request digest and durable outcome; duplicate receipts never change the canonical event's receipt rank or fields. Business errors return a message object with 400 and commit a rejected receipt plus scoped diagnostic. Request digests are not global dedupe keys. No raw JSON/base64 is retained in carrier_receipts. Normalized event provenance lives on accepted events; restricted CSV files retain their original source bytes.

## Matching, transaction and ordering

Resolve carrier/account through retained trusted ownership, verify active shipper/carrier, lock the shipper and match all four carrier/account/shipper/reference fields. Never fall back to a carrier number. Unknown accounts or unmatched packages produce durable errors without creating shipments, events or areas. No delayed event replay is scheduled if a package is created later.

P7 CSV row sequence values and webhook receipt sequence values are allocated before business execution from the shared global sequence. A nested savepoint rolls back invalid effects while diagnostics/outcomes commit. Accepted event/action/time uniqueness is enforced in PostgreSQL. Exact duplicates are checked before auxiliary corrections and have no business effects, even with changed signer/notes/number/route/deadline/image input. Distinct actions/times retain all history. Shared tenant locks plus uniqueness guard concurrent duplicates.

Source formats reuse explicit MM/DD/YYYY h:mm:ss AM/PM and canonical ISO datetime parsing; event time must include a time. Deadlines additionally accept canonical/source dates. Stored recipient validation timezone supplies naive-input interpretation, with missing zone UTC fallback and explicit offsets retained. Invalid zones/ambiguous/nonexistent local times reject atomically. An already-accepted source timestamp/action/package keeps its original normalization if address validation later changes timezone, avoiding a new event on an identical source retry. Canonical equivalent instants also dedupe.

Number, signer, notes, deadline and route use per-field last-valid-receipt guards. Missing fields do not advance a guard. Late completion of an older accepted row cannot replace a newer correction, including across manifests/carrier CSV/webhooks. Original addresses and carrier/account/tenant assignment never change. Route names normalize under the matched shipper, reuse active/deleted area IDs without restoring deleted rows, and create only genuinely missing names. An obsolete route receipt does not create an unused area.

Actual delivery time is selected only from delivered actions by event time/receipt ties; attempts never populate it. Returned retains historical delivery/time/signer while query reduction reports Undelivered. Later Delivered restores Delivered if time/name are complete; missing signer preserves existing nonempty data, or remains incomplete/Undelivered when no name exists. Nonterminal actions do not undo terminal outcomes. Existing P5/P6 reads immediately reflect event history, status, deadlines, routes and full-filter metrics; Void remains the overriding classification. No image readiness is invented.

## OnTrac CSV

Register an active carrier with configure --adapter ontrac_csv; register Paychex with the default paychex_manifest. Source identity comes from trusted configuration, never CSV company/address columns. A single OnTrac source may serve several shippers; account resolution and route creation remain separate for each shipper. Required headers are account/reference/event/timestamp; other documented carrier fields are optional, and unrelated columns are ignored.

P7 final rename, locking, snapshots, source-scoped content dedupe, independent polling, per-row recovery, partial outcomes and archives are reused. CSV fields are capped at 6,666,668 characters within the existing 20,000,000-byte file/20,000-row bounds, ready for P9's base64 envelope; manifests retain 65,536-character field bounds. The underlying process-global CSV parser ceiling is fixed so adapter limits cannot race across workers.

Rows record accepted/duplicate/ignored outcomes. rows_completed includes all three valid outcomes; rows_duplicate/rows_ignored are subsets, with rows_completed + rows_rejected = rows_total on ordinary completion. Unknown events do not make a partial file. Rejected business rows do; errors record trusted carrier/source/import/row and resolved shipper where available, account/reference and a reason only. Failed infrastructure retries preserve all completed row states/orders; accepted events are never resent on archive retry. Unmatched rows stay rejected even if a package is created later. See FILE_INGESTION_IMPLEMENTATION.md for storage repair and bounds.

## P9 integration

P9 replaces P8's temporary image-stage gate. Matched new images validate/resize before business effects and enqueue durable pending image work in the event transaction. Invalid image rows are terminal rejections while other CSV rows continue; valid tracking is preserved during later storage failures. Unknown/duplicate/unmatched inputs still create no image work. P8-era recorded rejections do not automatically replay after the upgrade. See POD_IMPLEMENTATION.md for the independent worker, image ordering and dummy URL limitations.

## Local startup and verification

Follow DEVELOPMENT.md for rebuilding, explicit migration, source registration and private mount ownership. Integration keys/accounts are operator supplied; no reference payload is imported into the development tenant. `sh scripts/verify-p8.sh` runs all synthetic PostgreSQL/Redis backend tests plus frontend lint/types/tests/build and HTTP smoke. Tests cover authentication/key replacement, tenant/account/reference isolation, exact/canonical/concurrent duplicates, terminal and ordinary-field ordering, historical ownership, deleted-area reuse, normalization stability, CSV partial/ignored outcomes and crash recovery. Actual counts/results/limits are recorded in tasks/plan.md. Real AWS, exports/SSE and full real-backend browser E2E remain their planned slices.
