# P6 shipper workspace UI

React uses the P3 authenticated workspace and P4/P5 APIs without new dependencies, backend routes or migrations. Existing login/session/logout behavior remains in place. The workspace mounts under verified company/user/role identity; changing that identity discards old filters, results and pending reads. Any protected query/mutation 401 closes the workspace immediately. Cookie mutations use the application CSRF header; backend authorization remains authoritative.

## Routes and navigation

- `/`: existing account overview with links to the delivered workflows.
- `/tracking`: Tracking filters, full-result metrics, server-sorted table and pagination.
- `/tracking/search`: exact identifier Search, default reference, with no hidden Tracking restrictions.
- `/tracking/detail/{identifier}?field=reference|shipment_number&shipment_id={id}`: retrieve the selected stable package ID through the authorized backend. A direct URL without shipment_id performs typed Search and displays the same ambiguity selection flow. Invalid selector/ID/encoded links show an error. Browser back/forward and ordinary modified/new-tab links are supported.
- `/areas`: company-shared active areas and administrator controls.

Identifiers are URL escaped and rendered as text; leading zeros, case and ZIP strings survive. Dot-only identifiers need a second encoded path component with `encoding=dot` because browsers normalize ordinary/percent-encoded dot segments. That marker also preserves direct lookup when selected identity is absent. The stable ID remains the backend retrieval identity and is reauthorized on each request.

Navigation uses React's external-store subscription to the History API; no routing library or server preference storage was added. Host deployments must serve index.html for frontend routes (Vite does this locally). The same-origin `/v1` proxy still supplies API transport. Query/address/history content is never persisted in browser storage.

## Tracking

Default dates remain omitted until an explicit Apply; the response supplies the effective UTC database day. The Sunday-first two-month picker has UTC presets, previous/next month, range highlighting, labeled date inputs, Cancel/Apply, complete/ordered validation, arrow-key date focus, Escape dismissal, focus containment and trigger-focus restoration. Presets follow DATE_FILTERS.md, including year/leap boundaries. On narrow screens the two months stack within a scrollable dialog.

Account is an exact text filter (no numeric conversion), Status is Delivered/Undelivered only, repeated active area IDs are OR selections and Exceptions is Attempted/Void/Returned. Groups combine through the P5 query. A committed filter or sort change resets page to 1; rows-per-page supports 10/25/50/100. Explicit reset restores default dates/filters. Unavailable selected areas are retained until the user explicitly clears them; rejection never silently broadens a query. Area option failures offer a reload.

Table headers apply supported server sort fields and expose aria-sort. Columns are frontend component state with Shipment always visible; no server flags/preferences or invented Driver field. Account is display-only because P5 does not support sorting it. Defaults show Shipment, Reference, Route, Company, City, Zip, POD Name, POD Time and visible Status text/dots. Due time and account can be shown. Full-filter Total/Undelivered/OTP come from the API, not page rows. Optional values render empty and incomplete delivery still displays its received time. Responsive tables scroll inside a labeled keyboard-focusable region.

## Search and detail

Search trims surrounding identifier whitespace and submits exactly one selected namespace. No match renders `The {identifier} does not exist` through React text interpolation. Singleton results open detail; multiple results display exactly seven columns beneath the form, with stable ID in each shipment link. Search pagination retains the committed lookup even while the form is edited.

Detail follows the two-column reference: status/attributes/history on the left, delivery/pickup addresses and POD on the right, stacking on narrower screens. It displays backend status including Void, original addresses, service/carrier/reference/weight (no inferred unit), repeated ordered history, delivery time and signer independently, and one image URL when supplied. Datetimes preserve the API's recipient-local wall time and explicit offset rather than converting to browser time. Null/unready POD has no image link; an invalid scheme or failed image shows an unavailable message. No map, favorite, address/deadline editing or outbound messages are included.

## Area management

Both roles see shared active options. Administrators see Add area and an Enable editing checkbox; edit/delete controls start off and reset off on reload or leaving/reentering the area screen. Add/edit name dialogs use the existing normalized API results, including restore and duplicate-edit no-op. Adding a deleted name restores through POST. Delete has a confirmation dialog describing preserved shipment links. Duplicate/validation/role/network failures remain visible and retryable; pending controls and a synchronous guard prevent duplicate mutations or closing while pending. Successful mutations refetch active areas and invalidate Tracking reads; Tracking state survives ordinary workspace navigation. Old area responses are ignored after unmount/company changes. P10 now embeds these controls in My Day and refreshes its combined statistics snapshot after mutations.

## Verification boundaries

Automated frontend tests use Vitest + React Testing Library/jsdom and synthetic JSON fixtures, including auth regressions, query transport, date range behavior, stable navigation, escaping, history/offset/POD failures, role controls, retry/pending guards, late reads and verified company switches. Fixtures are read-only test data, not database seeds or production UI data. Compose mounts frontend/tests read-only alongside src for consistent local checks.

`sh scripts/verify-p6.sh` runs the complete PostgreSQL/Redis backend regression suite followed by the standard lint/format/type/frontend/build/live-health checks. Browser visual inspection uses a temporary loopback static-build preview with synthetic API responses; it cannot modify the development database. Browser controls use the app's computer-use browser API (including its Playwright-style locators), not an installed Playwright E2E suite. Existing live credential-safe HTTP smoke checks real login/queries separately. Full browser-to-real-backend shipment E2E remains P12.

P9 now supplies selected ready POD URLs through the same detail contract (the default adapter returns non-downloadable dummy URLs). P10 now supplies My Day/area metric charts; P11 now supplies queued export/SSE and download controls. P6 does not fabricate those results or acceptance flows. Actual results and limitations are recorded in tasks/plan.md.

P10 replaces the authenticated root overview with My Day. See [DASHBOARD_IMPLEMENTATION.md](DASHBOARD_IMPLEMENTATION.md) for snapshot contracts, chart semantics, refresh triggers and verification boundaries.

P11 adds Tracking Export CSV and workspace-wide requester-scoped readiness/recovery cards with Click here to download. See EXPORT_IMPLEMENTATION.md for the SSE/REST lifecycle and actual task-plan checks.
