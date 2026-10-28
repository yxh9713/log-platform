# My Day

## Purpose and layout
Show the shipper's due-today package overview across carriers: Total, Undelivered, OTP, Exceptions chart and active area cards. Use consistent request/reporting date and snapshot within a response. No current-hour/last-updated label is required.

## APIs and metrics
GET /v1/shipment-stats returns total, delivered, undelivered and otp. GET /v1/exceptions-stats returns active attempted/returned/void counts and consolidated/no_package/held keys set to 0.

All My Day populations require verified shipper_company_id and due_date=today UTC. Count packages once, not history rows. Total includes Void; Delivered/Undelivered apply to non-Void packages. OTP excludes Void and uses current Delivered final-time strict comparison. Apply eligible-empty→0 and eligible-nonempty/no Delivered→100; otherwise calculate the delivered-based percentage to two decimals. See [STATUS_RULES.md](../STATUS_RULES.md).

Exceptions classify Void once first, exclude current Delivered, then inspect each remaining package's one latest event across all actions. Latest attempted or returned counts once; historical repeats do not accumulate.

## Area cards
GET /v1/area-stats lists active saved company areas alphabetically, including zero-shipment areas. NULL/deleted-area shipments remain in global totals but have no active card, so card sums can be smaller than global total. Carrier input matching a deleted area does not make its card reappear.

Administrators can Add area and toggle enable to reveal edit/delete controls. Editing is off after page reload. All users share read access; server enforces administrator mutation permission. Complete area behavior is in [004-areas.md](004-areas.md).

## States and acceptance
Show loading, error and empty states. Test tenant isolation, UTC boundary, all-Void and incomplete-POD metrics, final-time OTP, delayed event/correction effects, repeated-event counts, zero chart placeholders and area/global reconciliation.

Use PostgreSQL aggregate baseline first; Elasticsearch is deferred. Freshness targets/caching/projection strategy are engineering/performance design, not a new status definition.

## P10 delivered
The root workspace renders My Day with accessible SVG status rings, six labeled exception bars and shared administrator area controls. The additive GET /v1/my-day bundles all panels in one snapshot; the three approved statistics routes are implemented as documented in [API.md](../API.md). Refresh occurs manually, on window focus/visible-tab return and at the next UTC midnight. The server decides the reporting date. No polling/SSE freshness guarantee or last-updated indicator is added. See [implementation details](../DASHBOARD_IMPLEMENTATION.md) and the task plan for actual checks.
