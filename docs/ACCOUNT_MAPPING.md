# Carrier Account and Service Mapping

## Entity
account_mapping fields are id, shipper_company_id, carrier_company_id, service VARCHAR(64), account_id. Account values are strings. The owner manually configures mappings after database creation; sample accounts/service codes are not seed assignments.

One current (shipper_company_id, service) resolves exactly one carrier and account. A (carrier_company_id, account_id) pair identifies one distinct shipper. Multiple service rows may share that same pair for the same shipper; do not blindly make the pair unique on a service-level table and reject valid associations.

## Manifest assignment
Determine shipper from the trusted registered source folder. Look up its Carrier ID service code, such as OPT.OPT, within that shipper and derive carrier/account. Do not require the manifest to provide an account or trust a company label as tenant identity.

## Creation API
Require account_number and carrier_id. carrier_id is a service-code selector, not a numeric carrier company ID. Resolve the configured carrier under the verified shipper, then validate and save the supplied account_number as shipments.account_id. Never auto-fill missing API account_number from the mapping. service_name is descriptive service_type, not a selector.

Missing/invalid service or account and mismatched assignments return HTTP 400 with a message object; invalid requests create no shipment. Missing account has exact response:
```json
{"message":"account is required"}
```
Other descriptive messages are engineering choices; never disclose another tenant's configured accounts.

## Carrier updates
Use authenticated carrier plus payload account to resolve shipper, then match the assigned carrier/account/shipper/shipper_ref. The webhook key remains account; create API key remains account_number. Both map to account_id. Unknown/ambiguous mapping has no guessed/global fallback.

## Mapping edits
Edits apply only to future shipments. Existing shipments and same-reference upserts retain original carrier/account. Retain historical associations so legitimate updates to those packages remain authorized. A new mapping never authorizes taking over another carrier's old package.

**Engineering choice:** version mapping assignments or retain equivalent historical account associations with guarded lookup. Keys, constraints and transactional enforcement are implementation work. No mapping management UI, auto-registration or seed account values are required.

## Verification
Cover same reference across shippers, same account string across carriers, multi-service sharing of one shipper account, conflicting mappings, missing account, exact error body, future-only edits, historical update authorization and concurrent deterministic assignment.

## P4 physical implementation
Current account_mapping rows link to retained carrier_accounts ownership rows; both enforce the required cardinalities. AccountMappingService.configure changes only current assignments and never deletes historical ownership. shipments.creation_service records the original selector for valid idempotent API retries after mapping edits. No accounts/mappings are seeded and no public management route is added. See CREATION_IMPLEMENTATION.md.
