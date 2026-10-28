# P12 verification and operational baseline

This slice verifies the completed MVP; it adds no business feature, migration, external service or production SLA. PostgreSQL stays canonical and Elasticsearch/AWS remain deferred. P12 adds an isolated real-backend browser/recovery harness, a measured synthetic query/export baseline, a cross-pipeline application test and trusted read-only diagnostics. Actual results are in tasks/plan.md; measured data is in verification/p12-performance.json.

## Repeatable commands and isolation
Run from the repository root with Docker available. Preserve the existing ignored .env and private development credentials. Build local images before starting the verification lab:

```sh
docker compose build api frontend
sh scripts/p12-lab.sh start
python3 scripts/p12-recovery.py
docker compose -p logistics-p12 -f compose.verification.yaml exec -T api python -m tests.performance_baseline --packages 10000 --samples 10
docker compose -p logistics-p12 -f compose.verification.yaml cp api:/tmp/p12-performance.json .local/p12/performance.json
sh scripts/p12-lab.sh stop
API_PORT=8001 sh scripts/verify-p12.sh
```

The standalone compose.verification.yaml must not be merged with compose.yaml. It uses project logistics-p12, its own PostgreSQL/Redis/network/volume, database logistics_p12, loopback ports 8012/5174 and ignored .local/p12 download storage. Known synthetic credentials exist only for synthetic lab state. Setup refuses non-test/non-lab database targets before migrations/seeding; tests verify this guard. Benchmark databases have generated p12_perf_* names and are dropped in finally. Never run fixture/performance modules against the development tenant. Lab stop removes only this dedicated project's containers/network/volume; it does not remove the development volume or user files. Local evidence remains under ignored .local/p12.

P12_API_PORT/P12_FRONTEND_PORT can override test ports. INTAKE_UID/INTAKE_GID must match the host owner of .local/p12/download, as for normal export storage. Run browser and outage checks before benchmarking; do not rebuild/recreate shared images or run outage tests while a benchmark is active. Concurrent local work affects measured timings. The regular application suite uses the existing p2_test_* disposable database harness and covers all prior migration/seed/tenant/retry cases.

## Real browser journey
Open http://p12.localhost:5174 in the app browser. The distinct hostname avoids replacing a normal localhost development-session cookie. These are explicitly disposable test logins: admin@paychex.example and user@paychex.example, company paychex, password synthetic-p12-browser-only. They are not development or production credentials. The lab contains only synthetic packages P12-0001/P12-0002 sharing P12-DUP; one is Delivered and one Undelivered, due on the server's current UTC date.

The executed journey used actual React, Vite proxy, FastAPI, PostgreSQL and export worker, with no mocked browser API responses:

1. Administrator login; My Day total 2, undelivered 1, OTP 100 and active/empty area cards.
2. Search by shipment number P12-DUP; seven-column two-match table; choose P12-0002 and verify its own reference/Undelivered detail and leading-zero account/ZIP.
3. Areas: Add Browser zone, enable editing, rename Browser renamed, confirm soft deletion and manually restore the same name. Reload restores the session and resets editing off.
4. Tracking: submit Export CSV while the isolated worker is stopped. Exact acceptance appears and the job stays pending without a false link. Resume the worker and recover readiness over SSE/REST; click the real download link. The downloaded file has seven exact columns and two package rows.
5. API restart with an open stream; verify durable state survives. Reload recovers the ready file. Deterministic frontend tests cover silent stream reconnection and healthy heartbeat handling.
6. Logout and ordinary-user login. Tracking shares both packages; Delivered filtering updates both metrics and row count to one; administrator area controls are absent while restored shared areas remain visible. Administrator exports do not appear for the other requester.
7. Ordinary-user My Day at 390×844: no page overflow, visible labels/counts, two due-today packages. Evidence screenshots and the downloaded synthetic CSV are retained locally. Browser tab closes and viewport resets afterward.

This is an executed browser E2E journey using the app browser controls (including its Playwright locator surface), not a newly installed unattended Playwright runner. The committed lab, fixtures and journey are reproducible; component tests remain Vitest/RTL/jsdom. Browser coverage is scoped to the journey above, not a cross-browser/accessibility certification.

## Recovery checks and fixes
scripts/p12-recovery.py asserts the actual test database identity before stopping anything and controls only the fixed logistics-p12 project. It restores its stopped services in finally.

- Redis outage: liveness remains 200; readiness becomes 503. Existing sessions, queries and PostgreSQL export acceptance continue; new login fails closed because the limiter is unavailable. Restart restores readiness.
- Export worker outage/API restart: an accepted job stays durable/pending, then produces a real two-row CSV when the worker resumes. No ready notification precedes publication.
- PostgreSQL outage: liveness remains 200; readiness/authentication return sanitized 503. Restart restores the existing session and identical downloadable CSV checksum.
- Cross-pipeline test: a partial manifest retains its valid package and archives to failed; authenticated carrier delivery accepts/resizes an image; exact duplicate changes have no effects; a POD storage interruption preserves Delivered status and independently recovers; My Day and an independently retried CSV export reconcile; repeated file content adds no package/event/image effects. Tenant/requester boundaries remain covered.

P12 found and fixed two recovery gaps. The development Uvicorn command now watches only /app/app and sets a five-second graceful shutdown limit, so test-file edits do not restart the API and open SSE streams cannot block shutdown indefinitely. The stable lab API disables source reload. A proxy can also leave a broken stream appearing open; SSE now emits observable heartbeat events, and a five-second client watchdog renews the stream and recovers durable REST state after at least 15 seconds without a frame. Healthy two-second heartbeats keep the stream open. Hidden-tab timer throttling can delay that threshold; focus/visible-tab/manual recovery remains available. No polling/SSE path regenerates ready files.

## Read-only operational diagnostics

```sh
docker compose exec -T api python -m app.ops.cli
docker compose --profile ingestion --profile exports ps
docker compose exec -T api alembic current
docker compose exec -T api alembic check
```

The trusted CLI reports schema version, UTC check time, migration head/timezone, enabled-source count, import/archive state counts, POD/export state counts, due work/oldest waiting time and ingestion-error counts by reason code. It emits no tokens, account/reference/contact rows, filenames/paths or image bytes. Database failure produces one sanitized unavailable JSON object and nonzero exit. It performs no retries/mutations or public API authorization bypass. Use it only from an already trusted operator environment.

Interpret health and business state separately: a running/healthy worker heartbeat is not proof that every file/row/image/export succeeded. Investigate failed/retry_wait queues, old due work and archive retry/exhaustion using the existing trusted intake/POD retry commands in DEVELOPMENT.md. Fix storage/source/configuration before retry; do not replay events to repair an image or re-export a ready file for notification trouble. Existing jobs retain sanitized reason codes. Diagnostics are evidence, not an alerting service; no external messages or monitoring accounts are provisioned.

## Performance methodology and limits
The benchmark creates 10,000 packages (8,000 target shipper/2,000 other tenant), 50,000 events, 10 areas per tenant including one deleted area, mixed current states and repeated carrier shipment numbers. Fixtures are synthetic snapshots in a disposable database, not tenant seeds. Recipient cardinality is deliberately small and timezone falls back to UTC; this is not representative of every production workload. After ANALYZE, each query has two warmups and ten timed runs at concurrency one. SQL statement counts include scope/date/area validation, aggregates and rows. p95 is the nearest-rank sample percentile; ten samples provide only a small local baseline.

Measured operations are default Tracking, account+area+Undelivered Tracking, My Day, repeated-number Search, selected-ID detail, and real streaming 8,000-row export. The report includes PostgreSQL version/architecture, visible CPU count, process high-water RSS and a Tracking-page EXPLAIN ANALYZE/BUFFERS JSON plan. Process RSS includes fixture/interpreter/setup and excludes PostgreSQL/container memory; it is not a per-request or bounded total-memory proof. The baseline is warmed/local/single-client with normal development services running. It does not establish cold-cache, high-concurrency, million-package, network, throughput, retention or production SLO guarantees. Measure those on deployment-equivalent hardware/data before tuning or adding derived stores.

Production configuration still needs disk/retention quotas, hard-crash temporary-file cleanup, file/image decoder resource isolation, real storage provider timeouts/public S3 controls, reverse-proxy SSE buffering/timeouts/connection budgets, trusted TLS/IP/rate-limit configuration, backups/restore drills and measured capacity. None are silently provisioned or certified by P12.

## Measured local results — 2026-10-28

| Operation | Median ms | p95 ms | SQL statements |
|---|---:|---:|---:|
| tracking_today | 348.970 | 362.442 | 5–5 |
| tracking_account_area_undelivered | 78.712 | 84.727 | 6–6 |
| my_day | 476.339 | 499.442 | 5–5 |
| search_duplicate_number | 5.879 | 7.416 | 3–3 |
| detail | 4.229 | 6.285 | 6–6 |

Streaming export: 8,000 rows / 540,073 bytes in 75.283 ms (one measured generation, not a percentile). PostgreSQL 17.6 (Debian 17.6-2.pgdg12+1); aarch64; 10 visible CPUs; process high-water RSS 168,920 KiB. Tracking-page EXPLAIN execution time: 8.577 ms; complete plan is in the JSON report.
