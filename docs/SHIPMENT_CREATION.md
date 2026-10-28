# Shipment Creation

## Input mappings
| Input | Target and validation |
|---|---|
| reference | Required stable string → shipments.shipper_ref, unique within shipper |
| account_number | Required string → validated shipments.account_id |
| carrier_id | Required mapped service code → assigned carrier |
| shipment_number | Optional string; preserve supplied value or generate on first creation |
| reference_two | Optional → shipper_ref2 |
| service_name | Optional → service_type |
| due_time | Optional → normalized deadline; derive due_date/default as specified |
| package.weight | Optional/NULL → NUMERIC(5,2) |
| from_address / to_address | Required sender/recipient customer records |

No route is supplied by manifest/API creation; initialize route=NULL. signature_required and sort_code have no MVP behavior. contact and address_three are excluded from the new address contract. General unknown-key rejection/ignore behavior belongs to typed request-schema implementation, not a new alias.

## Normalization and weight
Trim surrounding string whitespace; preserve identifier case/leading zeros. Optional blanks become NULL on initial creation. Required strings that become empty fail validation. Existing-update omitted/empty/null fields preserve values.

Weight is optional, finite and nonnegative, including zero. Round using decimal arithmetic to two places; 56.789 becomes 56.79. Maximum persisted value 999.99 is sufficient. Reject negatives and rounded overflow, never clamp. Do not infer or convert lb/kg or require a unit.

## Addresses and customer reuse
Both addresses require name, address_one, city, state and zip. address_two, note, phone and email are optional. Trim before matching/inserting; optional whitespace-only address_two becomes NULL.

Store addresses in customers. from_address links customers.id to shipments.sender_id; to_address links it to shipments.recipient_id. Reuse an existing customer when the same verified shipper and normalized name/address_one/address_two/city/state/zip match. NULL address_two values compare equal for reuse. Matching is exact after trimming; do not apply area-name lowercasing or numeric ZIP conversion.

Name maps to the existing customers.company storage field. Add missing address_two/note/phone/email fields in the target model. No contact/address_three persistence is required. Optional metadata is not part of the six-field reuse key and must not create duplicates or overwrite an existing shared customer on reuse.

Use concurrency-safe reuse/insertion. Shipments' sender/recipient pointers and original customer address fields are immutable after creation. Later address validation can maintain validated_id/coordinates/timezone without changing the original address. Never attach another tenant's customer row.

## Shipment number generation
If absent on first successful API creation, generate a unique random 12–15 character string using uppercase A–Z and 0–9. **Engineering choice:** use 15 cryptographically random characters, collision detection and concurrency-safe reservation. Check uniqueness at generation; do not prohibit later carrier-supplied duplicate numbers under distinct references.

D49: an existing-reference create API request returns the existing package unchanged, even if it supplies a new number or other nonempty creation fields. Never generate a replacement, an extra Created event or a new default deadline merely because processing repeats.

## Transaction and lifecycle
Validate the request/row before shipment/customer/Created-event business effects. Persist one package by the stable shipper/reference key. New creation emits Created once at initial system processing UTC time. Invalid requests/rows record diagnostics separately; other valid CSV rows continue.

Carrier events, number changes, signer/POD, notes, route and explicit deadlines follow their separate authorized update rules. No general address editing is part of the MVP. D49 confirms creation API retries do not apply any edits; authorized manifest/carrier updates remain separate.

## Reference and verification
[Current example](reference/shipment-create-current-example.json) reflects the new fields; [original example](reference/shipment-create-request.json) remains historical. Neither is live seed data.

Verify NULL/zero/rounding boundaries, required address values, trimming, six-field reuse with NULL equality, concurrent reuse, tenant isolation, immutable shared addresses, generated-number format/collisions, stable retries, reference-priority conflicts and one-time creation effects.

## P4 implementation
POST /v1/shipments is implemented with 201 new / 200 unchanged valid existing-reference responses. It validates required account/service values against original or current tenant assignments while preserving historical ownership. Engineering DTO/error/format limits, database guards and verification details are in CREATION_IMPLEMENTATION.md. No reference payload is installed as tenant seed data.

D50 confirms manifest service description and source order date are creation-only. Existing manifest upserts preserve both while allowing the explicitly authorized nonempty number/notes/deadline corrections.
