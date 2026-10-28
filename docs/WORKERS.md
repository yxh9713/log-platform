# Background Work

## Jobs
| Job | Input | Output |
|---|---|---|
| Manifest import | Registered finalized Paychex CSV | Created/upserted packages, customer links, import diagnostics |
| Carrier CSV import | Registered OnTrac file | Accepted events/associated fields and outcomes |
| Webhook ingestion | Durable authorized carrier receipt | Matched accepted event or ignored/error outcome |
| POD storage | Prepared valid image linked to accepted event | Same image row URL/readiness or bounded retry failure |
| Shipment export | Verified requester/company and normalized filters | CSV file, durable readiness and SSE notification |
| Derived-state maintenance | Accepted shipment/event changes | Rebuildable summaries/metrics as needed |

## Scheduling and durability
Poll configured sources every 60 seconds by default with independent intervals and safe claims. The export queue is not the source-file polling schedule. Separate scheduler authority from API replicas; avoid duplicate dispatch.

Persist acceptance/outcomes in PostgreSQL. Redis can support broker/cache/live distribution; choose library during scaffolding. At-least-once delivery requires idempotent effects, bounded transient retry and clear terminal business outcomes.

## Shared guarantees
Use account/carrier authorization before mutation. Unique reference upsert and event triple dedupe are transactional. Event outcome selects event_time/receipt ties; deadline/ordinary fields respect last-valid receipt guards. Retries never regenerate identifiers/default deadlines or refresh duplicate event rank.

Unknown events are ignored; unmatched shipments are PostgreSQL error-only, not delayed-event queues. Invalid rows do not roll back other valid rows. Follow FILE_INGESTION.md for .part readiness, partial→failed, archive identity and move recovery.

## Images and exports
Image retries update one pending accepted image without another tracking event. Older upload completion cannot replace a newer current POD. Real S3 adapter is deferred.

Export queries full filtered results without pagination and streams/batches CSV generation. Notify only after file-ready state is durable. SSE reconnect/notification failure must not lose the artifact or trigger unnecessary CSV regeneration. Notification transport is not canonical readiness storage.

## Diagnostics and verification
Correlate jobs, imports, receipts and events; redact secrets/images/PII. Track accepted/rejected/duplicate/ignored counts, retry attempts and failure reasons. Test concurrent workers, reverse completion, duplicate delivery, mid-file crash, storage outages, SSE reconnect and reconciliation from PostgreSQL.

## Deferred jobs
Outbound carrier submission and Elasticsearch indexing/reconciliation are outside MVP. Address validation is an existing external workflow dependency that supplies validated-address metadata; do not invent a geocoding service or provider integration during this build.
