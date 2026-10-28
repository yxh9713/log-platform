# P5 shipment query implementation

These engineering interfaces implement the Tracking, identifier Search and detail contracts. OpenAPI at `/docs` describes all field types. Authentication uses P3 cookie or bearer sessions, current active shipper membership and server-derived tenant scope. Both administrator and user may read. Responses and errors use `Cache-Control: no-store`; SQL failures return sanitized 503 message objects.

## Tracking

`GET /v1/shipments` returns `items`, numeric `total/page/length/pages`, effective `start_date/end_date/date_type` and `metrics` (`total/delivered/undelivered/void/otp`). Metrics cover the full filtered population. Each row has a string stable `id`, string `shipment_number/reference/reference_two/account`, carrier display name, optional service_name, route_id/route label, recipient company/address fields, status, pod_name, deliver_time, due_time, due_date and decimal weight (JSON string, no inferred unit).

Parameters:

- `start_date` and `end_date`: strict YYYY-MM-DD, both absent means database today UTC, otherwise both required and inclusive. Reversed/invalid ranges return 422.
- `date_type`: due_date (default), order_date, deliver_time or created_at. Date columns compare inclusive dates; timestamp columns compare UTC start midnight through exclusive midnight after the end. NULL dates do not match. Recipient display zones never change filtering.
- `account`: exact string, including leading zeroes; no implicit trimming or numeric conversion.
- `status`: delivered or undelivered. Void is a distinct result status and never matches either option.
- `exception`: attempted, returned or void, using STATUS_RULES.md predicates.
- repeated `area`: positive signed-BIGINT IDs, at most 100 entries; duplicates collapse. OR within selection, AND across groups. Any missing, foreign or deleted area rejects the whole request with 400 `Invalid area selection`. No selection retains unassigned/deleted-area packages.
- `page`: 1..2147483647, default 1. `length`: 1..100, default 10. Out-of-range pages return empty items with the requested page and unchanged counts; an empty population has pages=0.
- `sort`: id, shipment_number, reference, route, company, city, zip, pod_name, deliver_time, due_time (default), status. `direction`: asc (default) or desc. NULLs last, stable numeric ID ascending as tie breaker. Text ordering uses PostgreSQL collation. Column choices remain frontend state.

Unknown parameters and repeated singleton parameters return 422; invalid filters never silently broaden a query. `export=1` now selects P11 durable export acceptance without pagination. Default/explicit `export=0` selects ordinary reads. Acceptance is emitted only after committing the durable job.

## Search and stable detail navigation

`GET /v1/shipments/search?identifier=00001&field=reference` returns `identifier`, `field`, `items`, numeric `total/page/length/pages`. `field` is reference (default, maps only shipper_ref) or shipment_number. Identifier whitespace is trimmed; case and leading zeroes are preserved. Search spans the tenant's entire history, including Void and deleted-area rows, with no Tracking date/account/area restrictions. Paging uses the same bounds/defaults as Tracking and stable ID ascending. No matches returns 200 with total=0/items=[]; the frontend safely renders `The {identifier} does not exist`.

Search item keys are `id` plus the seven approved display columns: shipment_number/reference/route/address_one/city/state/zip. `route` is a label, including a deleted area's label. ID is navigation metadata, not an eighth display column. When total=1 the frontend can redirect immediately; when total>1 it renders the selection table and pages all matches rather than choosing one arbitrarily.

`GET /v1/shipments/{shipment_id}` takes the selected **stable internal ID**, never an ambiguous number. Missing and foreign IDs both return 404 `Shipment not found`. No query parameters are accepted. The public frontend URL remains `/tracking/detail/{identifier}`. P6 wiring should carry `field=reference|shipment_number` and selected `shipment_id` in query/state; for a direct URL without selected identity, call Search first and use the same ambiguity flow. Treat the chosen stable ID as the retrieval identity and recheck authorization on every read.

Detail extends the Tracking row with `sender/recipient` original address objects (name/address_one/address_two/city/state/zip/note/phone/email), `history`, notes, order_date, created_at and nullable `pod_url`. Carrier maps company.name; service description maps shipments.service_type; reference_two maps shipper_ref2; company/address fields in list/Search map recipient. There is no approved driver field in the current model, so it is not an invented column/sort. History objects have string id/receipt_order, action label and event_time; newest event time first, then receipt order descending. Repeated distinct actions remain visible. Datetimes use actual recipient-local offsets (including DST) or explicit +00:00 UTC; due_date stays UTC. Incomplete delivery retains available time/name. Addresses and deadlines have no edit endpoint here.

## Query consistency and staged dependencies

PostgreSQL selects the latest terminal and latest overall action separately by event_time/receipt_order. One package stays one row before all filters, metrics and pagination. Void overrides status; Returned overrides retained delivery fields; otherwise nonempty signer plus delivery time gives Delivered. Nonterminal events preserve delivery outcomes but may suppress exception counts. OTP follows the strict deadline and non-Void special cases with two-decimal HALF_UP rounding. A repeatable-read transaction shares one database snapshot across scope validation, effective report date, totals, page, addresses and history.

No schema migration, seed change or external service is needed in P5. The read projection consumes the canonical final delivery fields; P8 will maintain these through authorized carrier ingestion, which is not implemented here. Fixtures synthesize history only in disposable databases. `pod_url` is always null in P5 because no image metadata/storage exists yet. P9 must connect this single-image contract to selected accepted delivery/event metadata, keep pending/failed URLs null and test late-upload completion ordering. P5 does not claim that image selection has been implemented. P10 adds My Day/area statistics and chart UI; P5 already supplies Tracking's required filtered metrics. P6 owns Tracking/Search/detail and area-control UI.

## Verification

Run `sh scripts/verify-p5.sh` for the entire PostgreSQL/Redis backend suite and `sh scripts/verify.sh` for lint, format, strict types, normal tests, frontend regression/build and live HTTP health smoke. Database tests create and remove isolated databases and never seed tenant shipments into the development database. See tasks/plan.md for actual results.

P11 update: filtered_population is now shared by list/metrics and asynchronous export. Export mode is delivered with durable acceptance and fixed effective dates; P5's original export rejection is superseded. The worker reuses accepted predicates without pagination and streams package rows. See EXPORT_IMPLEMENTATION.md.
