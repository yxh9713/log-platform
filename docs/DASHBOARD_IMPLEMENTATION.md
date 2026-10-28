# P10 My Day implementation

My Day is the authenticated root workspace. Verified active shipper membership scopes every package to shipper_company_id across all assigned carriers. PostgreSQL determines today in UTC independently of the session/browser timezone. Every response uses one repeatable-read snapshot, including membership, date, global metrics, exceptions and active area cards. No schema, seed or dependency change is needed; Alembic remains 0006_pod_images.

## Metrics and population
The shared QueryService population has one row per package and selects action history by event_time then receipt tie order. My Day filters due_date to the server reporting day; explicit Tracking date/filter populations retain their existing meaning. Shared metric expressions avoid separate status/OTP definitions.

Total = Delivered + Undelivered + Void. Void has precedence and is excluded from OTP. Eligible-empty OTP is 0; nonempty eligible populations with no Delivered packages have OTP 100. Otherwise OTP is currently Delivered packages strictly before due_time divided by currently Delivered packages, rounded to two decimals. Equal deadlines are late. Missing required delivery time/signer remains incomplete. Storage readiness does not change delivery status.

Exceptions count Void once first, exclude Delivered, and classify remaining packages by their latest event across all history. Only latest attempted/returned contribute; earlier repeats and latest nonexception actions do not. Consolidated, no_package and held remain literal zero placeholders.

Active saved areas are listed alphabetically, including empty areas, with a grouped left join. Empty/all-Void cards have OTP 0. NULL/deleted-area packages remain in global metrics but have no active card. Area totals can therefore be smaller than global totals. Tenant-separated names/IDs and all prior mutation/restore rules remain enforced.

## API and UI
[API.md](API.md) records the three approved statistics shapes and additive /v1/my-day bundle. The UI uses the bundle to avoid mixing dates or commits across panels. Separate approved route requests each have their own snapshot. Responses are no-store; unknown query parameters reject rather than implying unsupported filtering.

Runtime DTO validation checks dates, integer counts, reconciliation, OTP ranges, stable unique area IDs and reserved zeros. Reads abort on unmount/company changes and ignore stale responses. Loading, empty, error/retry and expired-session states are explicit. Status rings use actual Delivered/Undelivered/Void counts, with a neutral empty ring and visible counts. Six exception bars have visible labels/counts and accessible summaries. These are SVG/HTML with no chart dependency. No fake data or current-hour/last-updated indicator is displayed.

Existing administrator area dialogs and Enable editing are shared with Areas. Changes refresh the combined snapshot and existing options revision; editing remains enabled during refresh and resets on remount/reload. Regular users only read cards. Manual refresh, focus, visible-tab return and a UTC-midnight timer request fresh server state. There is no polling/SSE freshness guarantee; delayed ingestion appears on the next refresh.

## Verification boundaries
Backend tests use real disposable PostgreSQL/Redis fixtures for mixed statuses, strict deadlines, incomplete delivery, event reduction, corrections/dedupe, UTC boundaries, concurrent snapshot consistency, empty/deleted areas, tenant/role/membership and multi-carrier ownership. Frontend Vitest/RTL/jsdom tests validate contracts, accessibility summaries, states, administrator refresh, stale responses, zero cases and midnight refresh. Browser inspection uses a temporary synthetic preview, without development database writes. Actual counts/results are recorded in tasks/plan.md.

P11 export/SSE and P12 real-backend browser E2E/performance remain separate. Aggregates currently compute the full report for each approved route; no production throughput or query budget is claimed. PostgreSQL is canonical and no Redis dashboard cache or Elasticsearch projection is introduced.
