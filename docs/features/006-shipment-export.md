# Asynchronous Shipment Export

## Request and acknowledgement
Export all packages matching the current Tracking filters, with export=1 and no pagination. Authenticate shipper membership and retain verified company/requester scope. Normalize filters/default effective dates before queueing so overnight processing does not silently move the requested reporting day.

Durably accept the job before response; do not run the full query/CSV generation synchronously. Return exactly:
```json
{"message":"we start to process data"}
```
HTTP 202 is recommended. Queue technology and recovery/status endpoint DTOs are implementation design; do not require a new response job-ID field that changes this supplied body.

## Worker output
Read PostgreSQL when the worker executes, applying the same predicates as the list/metrics without pagination. No request-time frozen row snapshot is required. Stream/batch large results and count packages once.

CSV column order:
```text
shipment_number,carrier,route,order_date,due_date,pod_name,deliver_time
```

Carrier joins company.name via carrier_company_id. NULL cells are empty, while valid zero/string values are retained. Preserve identifiers and CSV quoting/newlines/escaping; apply spreadsheet-safety handling without changing source data. Nullable/deleted-area enrichment must not drop shipments.

**Engineering recommendations:** export readable area.name for route, including deleted-area label; serialize deliver_time using the normal offset-aware time contract; use UTC generation date and job-specific suffix/subdirectory to avoid same-day filename overwrites. These are formatting/storage design, not additional required columns. Do not synthesize source order_date from processing time.

## Storage
Development writes an actual CSV under local sftp download storage and returns a dummy URL, e.g. /paychex/download/shipment-{YYYY-MM-DD}.csv. Keep download files separate from intake upload/done/failed folders. Link artifact to job/requester and verify actual local serving during implementation; documenting a dummy path does not prove it is a working endpoint.

Future production storage uploads CSV to S3 and returns a public URL. AWS setup remains deferred. File-ready state follows successful generation/storage; failures must not produce a false ready event/toast.

## SSE and toast
Notify the authorized requesting dashboard over SSE when ready. Show a clickable toast with text **Click here to download** and the artifact URL. No Pusher account/credentials are needed.

Keep PostgreSQL job/readiness durable and tenant/requester-scoped. Redis can distribute live notifications; disconnect/reconnect cannot erase an already-created file. Define event payload, authenticated stream and recovery/status DTOs during implementation, consistent with portal token/session design. Do not put access tokens in public URLs or trust client subscription company IDs.

Notification retries must not regenerate/overwrite an already-ready file. A failed notification is not a failed export. Recover ready-job state on reconnect/reload without leaking another user's artifacts.

## Acceptance criteria
Full filters/no pagination; one package per row; exact seven columns; empty NULL and preserved zeros/leading zeros; correct quoting; nullable/deleted area enrichment; durable acknowledgement; local real CSV/dummy URL; ready toast only after storage; retry/reconnect recovery; bounded worker memory and tenant/job/download isolation.

## P11 delivered
Implemented with PostgreSQL durable jobs, optional local export worker, actual authenticated local CSV downloads, and cookie-authenticated SSE snapshot/recovery. Engineering DTOs, paths, bounds, local URL, file publication and dismissal semantics are in [EXPORT_IMPLEMENTATION.md](../EXPORT_IMPLEMENTATION.md) and OpenAPI. No new business rule or external storage account is introduced. See tasks/plan.md for actual verification results and production limitations.
