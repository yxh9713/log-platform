# API Contract

## Contract boundaries
Preserve routes/messages in the approved-route table. Exact additional DTOs, stable internal-ID detail retrieval, typed Search transport, SSE/job recovery paths and success acknowledgements not supplied by the owner are implementation interface work. Define them together in OpenAPI before their slice is built; do not infer a new business rule from a missing endpoint spelling.

All protected dashboard APIs require verified shipper membership. All counts/joins/filters use server-derived tenant scope. Public carrier receipt requires routed integration authentication and assignment authorization.

## Approved routes
| Method/path | Behavior |
|---|---|
| POST /v1/login | Email/password/company slug; token response; invalid login 401 |
| GET /v1/session | P3 engineering addition: verified shipper Principal, cookie or bearer |
| POST /v1/logout | P3 engineering addition: revoke current session and clear cookie |
| POST /v1/shipments | P4 creation, 201 new / 200 unchanged existing reference |
| GET /v1/shipments | Paginated tenant Tracking list or export=1 queued full-filter mode |
| GET /v1/shipment-stats | My Day global due-today counts/OTP |
| GET /v1/exceptions-stats | My Day exception counts and reserved zero categories |
| GET /v1/areas | Active company area options, alphabetical |
| POST /v1/area | Administrator create/restore |
| PUT /v1/area/{id} | Administrator edit; duplicate no-op supported |
| DELETE /v1/area/{id} | Administrator soft-delete, idempotent response |
| GET /v1/area-stats | Active area due-today counts/OTP, including empty areas |
| POST /v1/webhook/{integrationId} | Raw integration ID, X-API-Key, carrier-only event receipt |

**Implemented P4 creation route:** POST /v1/shipments. New packages return 201; valid existing-reference retries return the existing package unchanged with 200 (D49). Typed acknowledgements, errors, defaults and persistence details are in [CREATION_IMPLEMENTATION.md](CREATION_IMPLEMENTATION.md). Frontend detail path is /tracking/detail/{identifier}; it is not itself a supplied backend endpoint.

## Login
```json
{"email":"email@example.com","password":"<password>","slug":"paychex"}
```
Successful minimal response:
```json
{"token":"<access-token>"}
```
P3 implements signed, durable eight-hour sessions, cookie/bearer transport, verified session retrieval and logout. See [AUTHENTICATION.md](AUTHENTICATION.md) for the implemented DTOs, errors, CSRF, rate limits and security lifecycle. Client role/company fields cannot override verified membership. The frontend uses HttpOnly cookies without storing tokens in JavaScript; same-origin cookie transport is ready for later SSE.

## Tracking filters
| Parameter | Behavior |
|---|---|
| start_date, end_date | Both absent→today UTC; otherwise both required, inclusive, valid and ordered |
| date_type | Defaults due_date |
| account | Exact account_id string match |
| status | One delivered or undelivered value; no status=void option |
| exception | Engineering query spelling: one attempted, void or returned value |
| area | Repeated IDs, e.g. area=1&area=2; OR within selection, active company-owned IDs only |
| page, length | List pagination; page starts at 1, default length 10 |
| export | 1 selects queued export, with no pagination |

Combine filter groups with AND. Omitted filter adds no restriction. NULL/deleted-area shipments stay in general results without selected areas; deleted explicit area IDs are rejected. Contradictory status/exception choices return no matches rather than silently overriding a filter.

Return metrics for full filtered results, not only current rows. Tracking OTP uses the same formula as My Day within the selected population, without a new due-today restriction. New response DTOs use correct numeric pagination types, rather than preserving a historical string per_page. Frontend owns selected columns/sort UI state; server validates supported sort fields.

## My Day and areas
My Day uses shipper_company_id and due_date=today UTC. Response has total, delivered, undelivered, otp; total includes Void. Exceptions has attempted, returned, void and consolidated/no_package/held reserved at 0. No currentHour/replacement label.

Area option shape:
```json
[{"id":1,"name":"sfo"}]
```
POST/PUT body is {"name":"SFO"}; normalized response is {"id":1,"name":"sfo"}. POST returns 201 new/200 restore, PUT 200 including duplicate no-op. DELETE and repeated DELETE return 200:
```json
{"message":"Area deleted"}
```
Active duplicate POST returns 400:
```json
{"message":"sfo already exist"}
```
Names are normalized and validated as specified in features/004-areas.md. Manual mutations require administrator. Deleted PUT/filter targets are rejected. Empty active areas remain in area-stats; P10 preserves area/total/delivered/undelivered/otp and adds stable id, explicit void and a response-level report_date.

## Creation and carrier payloads
Use SHIPMENT_CREATION.md and the current request reference. Required account_number/carrier_id/reference and both addresses; optional shipment_number generated when missing, nullable weight/reference_two/service_name, optional due_time defaulted/normalized. Input reference maps shipper_ref, not a new reference column.

Webhook fields include account, event, time, shipment_number, reference, sign, pod, notes, optional route and due_time. CSV equivalent uses timestamp, zone and pod_image. Match carrier/account/shipper/shipper_ref first. Carrier deadline corrections require known event/time; no deadline-only messages. Invalid supplied deadline/image or required input rejects before partial business effects.

Missing/incorrect API key returns 401:
```json
{"message":"Invalid API key"}
```
Missing creation account returns 400:
```json
{"message":"account is required"}
```
Other input errors use descriptive message objects; status/message consistency is implementation DTO work. Wrong tenant/resource must not disclose another company's data. Unknown event is ignored; unmatched shipment creates PostgreSQL error only. Preserve exact duplicate-event semantics even if auxiliary payload differs.

## Search and detail

P5 implements GET /v1/shipments, GET /v1/shipments/search and GET /v1/shipments/{shipment_id}. Typed filters, sorts, pagination, full-filter metrics, selected-row navigation and detail DTO mapping are defined in [QUERY_IMPLEMENTATION.md](QUERY_IMPLEMENTATION.md) and OpenAPI. P9 now supplies the one selected POD URL after storage readiness; P11 now accepts export=1 with the exact supplied 202 body and no pagination.
Search selector is shipment_number or reference (default), matching only that field. One match redirects to /tracking/detail/{identifier}; no match shows The {identifier} does not exist. Multiple matches show shipment_number/reference/route/address_one/city/state/zip and clickable row identity. Use typed context and stable package identity so duplicate numbers cannot open an arbitrary detail.

Detail returns current status, shipment/address/history fields and one latest relevant POD URL. Void is shown for deleted_at. Preserve available delivery time even when POD name is missing. Backend retrieval DTO/path and presentation label mapping are implementation contracts constrained by features/003-search.md and 005-shipment-detail.md.

## Export and notification
With export=1, accept all filters without pagination, durably enqueue and return exactly:
```json
{"message":"we start to process data"}
```
HTTP 202 is the recommended acceptance status. Worker creates the specified seven-column CSV, stores it and notifies the authorized requester over SSE. Frontend toast is Click here to download. Do not add an obligatory response job ID or claim file readiness before storage succeeds. Define SSE event/job/status/download DTOs during that slice without changing this initial response.

## Time and references
Datetimes use recipient-local actual offset; missing timezone uses UTC +00:00. due_date/reporting stays UTC. Original reference JSON/CSV examples are unchanged historical input, not a second response schema or real seed data.

## Implemented P8 carrier receipt
POST /v1/webhook/{integrationId} is implemented with live X-API-Key authentication and synchronous durable accepted/duplicate/ignored outcomes (HTTP 200), rejected business diagnostics (400) and sanitized infrastructure failures (503). Exact input/body/response contracts, ordering and P9 image integration are in CARRIER_INGESTION_IMPLEMENTATION.md and OpenAPI. Carrier CSV uses the same domain transaction and P7 lifecycle. P9 supplies validated image preparation and independent storage retry.

## Implemented P9 POD handling
Carrier pod/pod_image accepts validated JPEG/PNG base64 up to 5,000,000 decoded bytes. Invalid images reject the whole update before business effects; valid prepared images commit pending with tracking and retry storage independently. Existing detail pod_url returns only the selected event-ordered image URL when ready, with null for selected pending/failed work. The default adapter returns a dummy .invalid URL without an actual upload. No new public content/history endpoint is added. See POD_IMPLEMENTATION.md.

## Implemented P10 statistics
All four GET routes require verified active shipper membership, reject query parameters (422), and return Cache-Control: no-store. The report_date is a PostgreSQL UTC date. Counts are integers; otp is a numeric percentage rounded to two decimals.

- /v1/shipment-stats: {report_date,total,delivered,undelivered,void,otp}.
- /v1/exceptions-stats: {report_date,attempted,returned,void,consolidated,no_package,held}; the last three are always 0.
- /v1/area-stats: {report_date,items:[{id,area,total,delivered,undelivered,void,otp}]}.
- /v1/my-day: {report_date,stats:{total,delivered,undelivered,void,otp},exceptions:{attempted,returned,void,consolidated,no_package,held},areas:[{id,area,total,delivered,undelivered,void,otp}]}.

The additive /v1/my-day engineering interface supplies the entire dashboard from one repeatable-read snapshot so its panels share a date and committed state. Separate calls to the three approved routes each have their own snapshot. Failures use existing typed auth/domain errors; database failures return 503 with “My Day statistics are temporarily unavailable”. See [DASHBOARD_IMPLEMENTATION.md](DASHBOARD_IMPLEMENTATION.md) and OpenAPI.

## Implemented P11 exports and SSE
GET /v1/shipments?export=1 durably queues all Tracking predicates and returns HTTP 202 with exactly {"message":"we start to process data"}. page/length are rejected in export mode. Cookie requests require X-Requested-With: logistics-web and an allowed supplied Origin. The acceptance body has no extra job ID. Effective dates are fixed at acceptance; generation reads packages later.

Engineering routes: GET /v1/exports (undismissed requester jobs), GET /v1/exports/{UUID} (status), POST /v1/exports/{UUID}/dismiss, GET /v1/exports/{UUID}/download (actual local CSV attachment) and GET /v1/exports/events (authenticated SSE). Foreign/unknown artifacts return 404; pending downloads/dismissals return 409. Limit 50 undismissed jobs per requester; acceptance beyond that returns 429. All access checks tenant AND requester, including same-company users. SSE reauthenticates, replays current durable snapshots after reconnect and never carries a token in a URL. Full typed shapes, storage/escaping/ordering, retry and SSE frames are in [EXPORT_IMPLEMENTATION.md](EXPORT_IMPLEMENTATION.md) and OpenAPI.

P12 SSE liveness amendment: event:heartbeat with data:{} is observable every unchanged two-second iteration; the browser renews silent streams and recovers durable REST state. Existing exports/session-expired/unavailable frames, authenticated scope and export/download shapes remain unchanged. No migration or business-rule change is required.
