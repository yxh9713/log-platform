# Tenancy and Shipment Identity

## Companies and roles
company.company_type is 1 for carrier and 2 for shipper. users.company_id establishes verified company membership; users.role_id references user_role administrator/user. Roles never grant cross-company access.

MVP dashboard queries use shipments.shipper_company_id=user.company_id and company_type=2. A shipper can have packages assigned to different carriers. Phase 2 carrier dashboard scope is carrier_company_id=user.company_id, not the shipper predicate.

## Package identity
| Input or field | Meaning |
|---|---|
| reference / manifest Package ID | Stable identifier stored in shipments.shipper_ref |
| shipment_number / manifest Order Number | Mutable carrier identifier stored in shipments.shipment_number |
| reference_two | Optional shipments.shipper_ref2 |
| shipper_company_id | Shipper tenant; legacy merchant_id meaning |
| carrier_company_id | Assigned carrier; legacy shipment company_id meaning |

Use UNIQUE(shipper_company_id, shipper_ref). Same key upserts one package; different references remain different packages even if shipment_number repeats. Never merge on shipment number alone or impose a hard unique constraint that rejects permitted source-number conflicts.

Preserve string identifiers and leading zeros. API creation may generate a unique uppercase alphanumeric shipment number; retries preserve the existing generated value. See [SHIPMENT_CREATION.md](SHIPMENT_CREATION.md).

## Carrier matching
Authenticate the raw-ID selected integrations row with X-API-Key. Derive carrier_company_id from integrations.company_id, resolve carrier/account→shipper through trusted mappings, and match all of:
```text
shipments.carrier_company_id = authenticated_carrier_id
shipments.account_id = received_account
shipments.shipper_company_id = mapped_shipper_id
shipments.shipper_ref = received_reference
```

No shipper slug is required in a carrier payload. No global reference/number fallback is allowed. Unknown shipment produces a PostgreSQL ingestion error and no shipment/event/image work. Unknown event code is ignored without business effects.

## Immutable assignment boundaries
Do not change tenant ownership, stable reference or original addresses through unchecked payload fields. Mapping changes affect new shipments only; existing-reference upserts retain assigned carrier/account and historical authorization lookup.

Customer reuse includes company scope. Areas belong to the shipper company and store integer route references. Verify joins, selected IDs, exports, detail links, notifications and artifacts against the authorized tenant even when source identifiers overlap.
