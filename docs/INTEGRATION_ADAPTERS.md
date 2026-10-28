# Integration Adapters

## Initial sources
| Source | Type | Trusted company |
|---|---|---|
| Paychex manifest | Shipper | Paychex, slug paychex, company_type=2 |
| OnTrac tracking CSV/webhook | Carrier | OnTrac, slug ontrac, company_type=1 |

These companies are approved development seed records. Example package/contact/account values are reference only and are not seed mappings or real data.

## Adapter structure
**Engineering recommendation:** separate transformer/loader modules per provider and flow:
```text
app/integrations/shippers/paychex/transformer.py
app/integrations/shippers/paychex/loader.py
app/integrations/carriers/ontrac/transformer.py
app/integrations/carriers/ontrac/loader.py
app/services/shipment_ingestion.py
app/services/tracking_ingestion.py
app/storage/pod.py
```

Keep authentication, tenant resolution, reference uniqueness, dedupe, transactions and status/deadline rules in shared services. Do not duplicate business rules in provider loaders.

## Paychex mappings
| Manifest column | Canonical handling |
|---|---|
| Carrier ID | shipper-scoped account_mapping.service → carrier/account |
| Package ID | shipments.shipper_ref |
| Order Number | shipments.shipment_number |
| Order Date/Time | Source order date/time; populate order_date only on creation (D50); never use as default-deadline base |
| Due Date/Time | Deadline normalization/defaulting |
| Pickup Name/Address/City/State/Zip | Sender customer lookup/reuse |
| Destination Name/Address/City/State/Zip | Recipient customer lookup/reuse |
| Destination Notes | Received notes; no undocumented splitting of delimiters |
| Service Type/Name | Descriptive service_type, creation-only (D50) |

Manifest/create flow supplies no route; do not infer one from Destination Route or an address. Removed third address line/contact fields are outside the target address contract. Preserve identifier/ZIP strings and trim input before customer matching. Full normalization is in SHIPMENT_CREATION.md.

## OnTrac event mappings
Ignore status. Map event to the shared action and timestamp to event_time for CSV:

| Raw value | Action |
|---|---|
| Possession | possession |
| OutForDelivery | out for delivery |
| Delivery | delivered |
| PickUp | picked up |
| Exception | attempted |
| Returned | returned |

The webhook also accepts the supplied Delivered→delivered mapping and uses time→event_time. Do not infer additional aliases/case folding. Unknown codes are ignored. Source CSV format includes MM/DD/YYYY h:mm:ss AM/PM; zone interpretation follows TIME_RULES.md.

| Carrier input | Canonical handling |
|---|---|
| account | Resolve shipper within authenticated carrier |
| reference | Match shipments.shipper_ref |
| shipment_number | Mutable carrier number |
| event, timestamp (CSV) / time (webhook) | Action and event_time |
| sign | shipments.pod_name |
| pod_image (CSV) / pod (webhook) | Base64 input to POD processing/storage |
| zone (CSV) / route (webhook) | Normalized area name → area.id |
| due_time | Optional deadline accompanying a known event/time |
| notes | Nonempty replaces; missing/empty/null preserves |

CSV zone 154 means area name "154", not database ID 154. Carrier address/contact columns do not change stored original addresses. Missing signer is accepted as incomplete delivery. Never use CSV order or timestamp as due_time.

## References
[Paychex manifest](reference/shipper-manifest-example.csv), [expanded OnTrac CSV](reference/carrier-status-pod-example.csv), [current webhook](reference/webhook-delivered-route-example.json), [current creation request](reference/shipment-create-current-example.json). Original earlier samples are retained unchanged; pod placeholders are not valid image test content.

## Storage and verification
Use POD_STORAGE.md for validation/900px resize, shipment_images.url, dummy adapter and independent retry. Use FILE_INGESTION.md for file readiness/archive/polling. Verify every exact mapping, auth/tenant/account boundary, default/invalid inputs, repeated events and no side effects for ignored/error outcomes.
