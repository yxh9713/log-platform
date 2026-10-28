# Ingestion Contracts

## Shared pipeline
```text
receive → identify/authenticate source → retain receipt → validate/map/normalize
        → resolve assignment/package → dedupe → commit accepted effects
        → update derived state → record outcome/archive
```

PostgreSQL stores durable receipts/imports/errors/jobs. Immutable raw source access is restricted; do not dump secrets, full rows or base64 into general logs. Shared services own transactions and business rules; provider transformers/loaders handle field layouts.

## Source identity
- Manifest: registered shipper folder/adapter gives shipper identity; service mapping gives carrier/account.
- Carrier CSV: registered carrier gives carrier identity; account mapping gives shipper.
- Carrier webhook: POST /v1/webhook/{integrationId}, raw ID plus X-API-Key for that integrations row; carrier/account mapping gives shipper.
- Dashboard/API: verified shipper membership gives tenant; required service/account inputs are validated.

Never trust an arbitrary company label/ID, skip assignment checks or fall back to global reference/number matching. Incoming reference is shipments.shipper_ref.

## Creation and updates
Create/upsert one package by (shipper_company_id, shipper_ref). New packages get immutable normalized customer addresses, supplied/generated number, required/defaulted deadline, NULL route and one Created event. See SHIPMENT_CREATION.md.

Existing shipments retain tenant, reference, carrier/account assignment and original addresses. Updates focus on mapped event/time and authorized number, signer/POD, notes, route and explicit deadline fields. Missing/empty/null preserves prior values. Nonempty notes replace, not append.

Permitted ordinary fields and deadlines use last received valid authorized update; lifecycle outcome uses event_time-first ordering. Preserve durable receipt order across retries/worker reordering. Same-reference upsert emits no extra Created or regenerated number/deadline.

## Event outcomes
| Condition | Required behavior |
|---|---|
| Known event with matched assigned shipment | Store distinct event and approved associated effects |
| Existing shipment/action/normalized-time tuple | Ignore entire duplicate update, no side effects/tie refresh |
| Unknown event code | Ignore without shipment/image/area/deadline effects |
| Known event, unknown assigned reference | PostgreSQL ingestion error; no shipment/event/image/area creation; no delayed automatic event retry |
| Missing signer with delivery time | Accept received data; remain Undelivered unless complete POD fields already satisfy rules |
| Invalid deadline/image/required input | Reject request/row before partial business effects; retain diagnostics |
| Transient image storage failure after valid acceptance | Retain tracking and retry pending image independently |

Tracking APIs must display available delivery time even for incomplete-POD Undelivered shipments. Do not fabricate signer values or clear history on return.

## Deadline and route mappings
Paychex Due Date/Time and optional create/carrier due_time map to deadline, never generic scan time. Carrier deadline corrections require normal event/time; no deadline-only flow. See DEADLINE_RULES.md.

Carrier CSV zone and webhook route are normalized area-name inputs. After matching existing shipment, resolve same-shipper area including deleted rows; create only a genuinely absent name; assign integer ID. A matching deleted area stays deleted. Omitted/empty/null preserves assignment. Duplicate/unknown events and unmatched shipments cannot create areas.

## File processing and errors
Follow FILE_INGESTION.md. Process valid rows despite invalid rows. All distinct carrier event/time combinations for one reference survive; never collapse a file to its last row per reference. Exact event triples already in memory/database are skipped.

PostgreSQL error records include trusted source/tenant/import identity, receipt time, row number when applicable, received account/reference and reason. Error records must allow absent shipment IDs. Link restricted original input/prepared content rather than storing raw base64 or sensitive row dumps in logs. Redis can support retries, not be the sole error store.

Partial imports go to failed/ with completed_with_errors and committed valid rows retained. Generic worker retries must not convert recorded unmatched/business errors into automatic delayed events.

## Verification
Cover all outcome rows, source/tenant isolation, missing versus malformed fields, immutable addresses, ordinary-field receipt order, concurrent reference upsert/event dedupe, stable normalization, partial file success and infrastructure failure recovery.
