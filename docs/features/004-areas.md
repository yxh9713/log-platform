# Areas

## Ownership and permissions
Areas are company-shared organizational labels for shipments. area.company_id is the shipper company; shipments.route is nullable integer area.id.

All company users can read options/statistics and filter. Only company administrators can manually create/edit/delete/restore. users.role_id references user_role administrator/user. The UI enable control is not authorization.

## Naming and identity
Trim and lowercase for storage/API output. Names are required, at most 64 characters, and allow letters, numbers, spaces, hyphens and underscores. Names are unique per company including deleted rows. Display may uppercase text without changing stored identity.

Renaming retains ID and shipment links. Active duplicate create returns 400 with normalized name in {"message":"sfo already exist"}. Duplicate edit is a 200 successful no-op that returns the actual resulting area rather than creating/merging duplicate rows.

## User flow and API
Add area opens a name modal. Enable toggles pencil/trash icons; editing defaults off and resets off on reload. Successful mutation refreshes affected options/cards/statistics.

| Method/path | Contract |
|---|---|
| GET /v1/areas | Alphabetically sorted active company id/name array |
| POST /v1/area | {"name":"SFO"}; 201 new/200 manual restore; return {"id":1,"name":"sfo"} |
| PUT /v1/area/{id} | Same name body; 200 actual id/name including duplicate no-op; reject deleted target |
| DELETE /v1/area/{id} | Set deleted_at; 200 {"message":"Area deleted"}; repeat succeeds identically |
| GET /v1/area-stats | Active sorted area cards, due-today counts/OTP including empty areas |

Reject unauthorized/cross-company IDs, invalid names and deleted explicit area filters without broadening results. Standard status/messages beyond supplied examples are API implementation design.

## Carrier assignment
Manifest/create API supplies no route, so initial route is NULL. Carrier CSV zone and webhook route supply normalized area names. After authenticating/matching an existing assigned shipment:
1. Find same-shipper area including deleted rows.
2. If found, assign that existing ID.
3. If absent, create the company/name safely and assign its ID.

Numeric zone 154 means name "154", not area.id=154. If sfo is deleted, an incoming sfo still assigns its existing ID while deleted_at stays unchanged. Never restore or duplicate it through carrier ingestion. Only manual administrator POST of that name restores the same ID/links.

Missing/empty/null preserves existing assignment. Accepted route updates use ordinary-field receipt order. Duplicate/unknown events and unmatched shipments create no area/assignment side effects.

## Visibility and metrics
Deleted areas are absent from options/cards/area stats and invalid as explicit filter IDs. Keep their shipments, NULL routes and global totals in general tenant/date results. Selected areas use OR across active IDs and never match NULL. Active card sums may be below global total.

Use STATUS_RULES.md for due-today company population, Void/count reconciliation and OTP eligible non-Void special cases. Empty areas return zero counts/OTP; all-Void areas have displayed total>0 but OTP0. Company area names are independent across tenants.

## Acceptance criteria
Role/tenant isolation; normalized duplicates/concurrency; exact CRUD responses; enable reset; alphabetical options/cards; immutable links on rename/delete; repeat delete and deleted PUT/filter rejection; carrier new/deleted-name assignment; no side effects from ignored/error events; NULL/general results; empty/all-Void metrics.

## P4 implementation boundary
P4 implements the area table/shared service and approved options/CRUD APIs, including server-enforced administrator and tenant checks, restore/no-op semantics and immutable shipment links. P6 delivers enable/modals/icons; P10 embeds those controls with due-today cards and refreshes the full snapshot after mutations. Trusted carrier auto-assignment is delivered in P8. See CREATION_IMPLEMENTATION.md.
