# Development Environment

## Delivered scope and versions
P1 supplies the React/Vite TypeScript startup page, FastAPI health endpoints, Docker Compose PostgreSQL/Redis services, and a test/tooling harness. P2 adds explicit Alembic identity/catalog migrations and an editable development seed CLI. P3 adds shipper login, durable sessions, logout and an authenticated layout. P4 adds shipment/address/account/area schema and creation/area APIs. P5 adds Tracking filters/pagination/full-result metrics, exact identifier Search and stable-ID detail APIs. P6 adds Tracking/Search/detail and administrator area UI. P7 adds an optional PostgreSQL-backed file scheduler/worker and local sftp mount for Paychex manifests; P8 adds authenticated OnTrac webhook and carrier CSV event ingestion; P9 adds a separate POD storage worker; P10 adds My Day aggregate APIs and chart UI; P11 adds queued exports/SSE and P12 adds integration/browser/recovery verification and diagnostics. PostgreSQL is canonical; Redis is disposable support. Elasticsearch and real AWS setup remain deferred.

Engineering choices: Python 3.12.12, uv 0.9.5, Node 24.10.0 (Node 24 required for host tooling), React 19.2.0, Vite 7.3.7, TypeScript 5.9.3, Vitest 4.1.12, FastAPI 0.162.0, Alembic 1.17.0, SQLAlchemy 2.0.44, argon2-cffi 25.1.0, itsdangerous 2.2.0, Pillow 13.0.0, PostgreSQL 17.6, Redis 7.4.6. Direct dependencies are pinned; `backend/uv.lock` and `frontend/package-lock.json` lock transitive dependencies. Container tags pin versions, not image digests. P7 uses PostgreSQL locks and durable checkpoints directly; it adds no queue dependency.

## Start locally
Install Docker with Compose v2 or newer and start its daemon. From the repository root:

```sh
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD and AUTH_SECRET to locally generated secrets.
# Database password: openssl rand -hex 24
# AUTH_SECRET (at least 32 characters): openssl rand -hex 32
# Never commit generated values.

docker compose config --quiet
docker compose up --build --wait --wait-timeout 180
```

Open [the frontend](http://localhost:5173) and [API OpenAPI docs](http://localhost:8000/docs). Health checks are also linked on the startup page. Set `FRONTEND_PORT`/`API_PORT` in `.env` if those host ports are occupied. Application ports bind only to loopback. PostgreSQL also publishes a loopback-only host port (5432 by default) for local database tools. Redis remains reachable only inside the Compose network.

`POSTGRES_DB` and `POSTGRES_USER` default to `logistics`; keep them simple alphanumeric names. The Compose connection URL requires URL-safe passwords; use hex as above, or percent-encode any reserved URL characters in the URL. `.env` is ignored, and `.env.example` has no usable password. Changing PostgreSQL credentials after initial volume creation does not change existing database credentials: use the original settings or explicitly administer the database.

Frontend and API run as non-root users with source files mounted read-only and hot reload enabled. Database and Redis images use their standard entrypoints to initialize and drop privileges. This is development tooling, with development dependencies and API docs enabled. Changes to dependencies, config or Dockerfiles require `docker compose up --build --wait` again. Browser requests use Vite's same-origin `/health` and `/v1` proxies; no permissive CORS or browser secrets are needed.

```sh
docker compose ps
docker compose logs --tail=100 api frontend
docker compose down
```

`down` preserves `postgres_data`. `docker compose down --volumes` explicitly destroys the local database; use it only when you intend a reset. Redis persistence is disabled; it is not durable job storage. No service automatically migrates schema or creates tenant data on startup. No SFTP daemon, AWS credentials or external notification account is required.

## Environment
| Variable | Purpose |
|---|---|
| POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD | Local Compose database settings; password required |
| POSTGRES_PORT | Loopback-only PostgreSQL host port for DataGrip/psql, default 5432 |
| DATABASE_URL | Backend PostgreSQL DSN, injected by Compose; sensitive |
| REDIS_URL | Backend Redis DSN, injected by Compose |
| AUTH_SECRET | Required session-signing secret, minimum 32 characters; runtime local value in ignored .env |
| AUTH_ALLOWED_ORIGINS | JSON array of exact allowed browser origins; local defaults cover localhost/127.0.0.1 ports 5173/8000; production requires HTTPS |
| APP_ENV | Seed CLI requires development; default production outside Compose, explicit development default in local Compose |
| APP_TIMEZONE | Must be UTC; database server and health-query session also use UTC |
| API_PORT / FRONTEND_PORT | Loopback host ports, default 8000 / 5173 |
| API_PROXY_TARGET | Vite server-only target, default http://api:8000 in Compose |

`backend/.env.example` documents DSNs for host-only API development; `frontend/.env.example` documents the proxy override. `AUTH_SECRET` signs sessions and keyed login-limit identifiers; rotate it to invalidate existing signed sessions. Never put secrets in `VITE_*` variables or committed files. Health responses never include DSNs or dependency exception details.

## Health contract
These P1 operational endpoints are engineering additions, separate from approved `/v1` business routes. Both have typed OpenAPI response models and require no login:

- `GET /health/live`: 200 `{"status":"ok"}`, independent of dependency availability.
- `GET /health/ready`: queries PostgreSQL with `SELECT 1` and Redis with `PING` in parallel. Each probe has a three-second overall timeout. Returns 200 when both succeed, otherwise 503. Body: `{"status":"ok|unavailable","dependencies":{"postgres":"ok|unavailable","redis":"ok|unavailable"}}`.

Compose gates API startup on healthy PostgreSQL/Redis, then frontend startup on API readiness. Frontend container health checks its HTTP server. Runtime dependency failures affect readiness while liveness stays available. These probes do not assert schema, migration, authentication or job readiness.

## Verification
After startup:

```sh
sh scripts/verify.sh
```

This runs backend Ruff lint/format checks, strict mypy (including migrations), unit pytest; frontend Prettier, ESLint, TypeScript, Vitest and production build; then HTTP smoke checks for the frontend, API and proxy with real PostgreSQL/Redis readiness. For custom host ports export matching `API_PORT`/`FRONTEND_PORT` before running the script; Python does not read `.env`. Tests mock dependency success/failure combinations and verify sanitized 503 responses, independent liveness and UTC validation. The UI test checks the scaffold and its accessible links. Database integration tests are skipped unless RUN_DB_TESTS=1; run the separate P2 verification below.

Individual container commands:

```sh
docker compose exec api pytest -q -p no:cacheprovider
docker compose exec api ruff check --no-cache app tests alembic
docker compose exec api ruff format --check --no-cache app tests alembic
docker compose exec api mypy --cache-dir=/tmp/logistics-mypy app tests alembic
docker compose exec frontend npm test
docker compose exec frontend npm run lint
docker compose exec frontend npm run typecheck
docker compose exec frontend npm run format:check
docker compose exec frontend npm run build
```

Host frontend alternative: `cd frontend`, `npm ci`, then the same npm scripts; `npm run dev` uses http://127.0.0.1:8000 by default. Host backend alternative requires Python 3.12 and uv 0.9.5: `cd backend`, copy `.env.example` to `.env` with real local DSNs, `uv sync --frozen`, then `uv run uvicorn app.main:create_app --factory --reload`. Use 127.0.0.1:POSTGRES_PORT for PostgreSQL in host mode and provide independently reachable Redis; Compose does not publish Redis. Run host checks with `uv run ruff check app tests alembic`, `uv run ruff format --check app tests alembic`, `uv run mypy app tests alembic`, and `uv run pytest`.

## P2 migrations and development users
After the stack starts, apply schema explicitly, then seed:

```sh
docker compose exec api alembic upgrade head
docker compose exec api alembic check
docker compose exec api alembic current
docker compose exec api python -m app.db.seed
```

The last command expects a real interactive terminal and displays new passwords once. Existing users keep their passwords, roles and activation state on reruns. `APP_ENV=development` is required (provided by local Compose); without it the command refuses to seed. Migrations create no catalogs, users or passwords, and do not require Redis. P2 creates company, user_role, users and shipment_actions; P3 adds auth_sessions in a separate explicit migration. P4 now adds the creation domain tables; query/ingestion/storage flows remain separate.

For noninteractive execution, select a NEW private destination instead of putting credentials in logs:

```sh
docker compose exec -T api python -m app.db.seed --credentials-file /home/app/initial-users.json
# Wait for successful completion before copying the file.
mkdir -p .local
chmod 700 .local
docker compose cp api:/home/app/initial-users.json .local/development-users.json
chmod 600 .local/development-users.json
```

Never overwrite an existing credential file. `.local/` is ignored by Git; the source file inside the container is ephemeral and is lost on container recreation. Preserve the private copy before rebuilding if these credentials are needed. A new credentials-file destination is required for every seed run; unchanged users produce an empty users array. Password reset is a separate future explicit operation, not a seed rerun. P2 execution for this workspace saved initial credentials privately to `.local/development-users.json`; passwords have not been displayed in chat or logs.

Editable declarations and preservation semantics are in [SEED_DATA.md](SEED_DATA.md) and `backend/app/db/seed_data.py`. P3 login uses the shared Argon2id helper in `app.passwords`. No sample shipments, contacts, carrier accounts, account mappings or integration keys are seeded. P3 tests login, session membership and the administrator dependency; actual area mutations remain later work.

Run P2's real PostgreSQL checks:

```sh
sh scripts/verify-p2.sh
# equivalent:
docker compose exec -T -e RUN_DB_TESTS=1 api pytest -q -p no:cacheprovider
```

Tests create randomly named p2_test_* databases using the local Compose database administrator, migrate/seed/check them, then drop only those disposable databases. They never downgrade or clear the development database. Use only a disposable local test server/account with CREATE DATABASE permission for RUN_DB_TESTS=1. The suite verifies empty/repeated upgrades, downgrade/re-upgrade, metadata drift, seed repeat/concurrency, real Argon2id password verification, role/tenant email links, FK/unique constraints, preserved manual settings, customizable declarations, transactional rollback and CLI credential/environment guards. P2 originally ran 23 tests; the evolving suite now includes P3. Normal pytest now runs 53 unit tests and skips 56 opt-in PostgreSQL/Redis integration tests. The full suite runs 109 tests.

For host mode, run `uv run alembic upgrade head` then `uv run python -m app.db.seed` from backend with local environment settings. Alembic uses online PostgreSQL connections only; offline SQL generation is deliberately unsupported in P2. User updated_at is initialized by PostgreSQL; later user mutation services must maintain it explicitly. Checks still report the upstream Starlette TestClient/httpx deprecation warning inherited from P1.

## P3 login and sessions
Apply `docker compose exec api alembic upgrade head` to reach 0002_auth_sessions, including when upgrading an already seeded P2 database. Open the frontend root, enter the seeded email/password and company slug paychex, then sign in. The private `.local/development-users.json` copy from P2 contains the initial credentials; seeding again does not reset or reveal them. No re-seeding is required for P3.

The session cookie is HttpOnly/SameSite=Strict (Secure in production); the frontend never persists tokens in browser storage. Reload/focus restores the verified session; eight-hour expiry returns to login; Sign out revokes the current session in PostgreSQL. The layout shows company and role without inventing shipment metrics or area operations. See [AUTHENTICATION.md](AUTHENTICATION.md) for exact API/security choices, CSRF and throttling. Configure AUTH_ALLOWED_ORIGINS when using custom frontend/API host ports. For host-only uvicorn, also pass `--no-proxy-headers` unless you have explicitly configured a trusted proxy.

```sh
sh scripts/verify.sh       # lint, format, types, unit/UI tests, production build and HTTP smoke
sh scripts/verify-p3.sh    # evolving backend suite with disposable PostgreSQL/Redis checks
# Optional live check: reads the two private seeded credentials internally, prints no secrets.
python3 scripts/auth_smoke.py --credentials-file .local/development-users.json
```

The live smoke logs in both seeded roles through Vite, restores cookies, checks direct bearer access and verifies logout revokes both transports. It creates and revokes real local sessions but does not change passwords or seed data. The full test suite covers generic invalid login, inactive/carrier membership, overlapping tenant emails, role changes, expired/tampered/revoked/rotated tokens, cookies/CSRF, login limits, service failures and OpenAPI response/security consistency. It also retains the P2 migration/seed tests. Redis limiter test keys are privately hashed, uniquely prefixed and removed after testing. Browser validation inspected the default login layout and a 390px mobile layout with no horizontal overflow; full authenticated browser E2E remains P12 work.

Production requires a strong AUTH_SECRET and explicit HTTPS origins. Local images remain development images (Vite dev server, reload, docs and database administrator account). Rate capacity/trusted proxy behavior and expired-session retention need deployment configuration; no production readiness is claimed.

## P4 creation, accounts and areas
The implemented schema/API contract is [CREATION_IMPLEMENTATION.md](CREATION_IMPLEMENTATION.md). Apply the explicit migration after rebuilding:

```sh
docker compose up --build --wait --wait-timeout 180
docker compose exec api alembic upgrade head
docker compose exec api alembic check
docker compose exec api alembic current
sh scripts/verify-p4.sh
sh scripts/verify.sh
# Read-only area verification for both existing roles, plus the P3 auth smoke:
python3 scripts/auth_smoke.py --credentials-file .local/development-users.json --check-areas
```

Head is 0003_creation_core. Migration creates schema, a sequence and immutability/number guards; it inserts no packages, addresses, account mappings, carrier accounts or areas. P2 seed behavior remains unchanged. Development users/passwords are preserved. Do not use reference package/contact/account samples as seed data. Test fixtures live only in disposable test databases.

POST /v1/shipments now creates a package (201) or returns the unchanged existing package (200) by verified shipper/reference, as confirmed in D49. You must configure actual owner-provided service/account assignments first via the trusted AccountMappingService helper or equivalent carefully constrained database administration; no accounts are auto-filled from examples. The helper's configure signature and physical history design are documented in CREATION_IMPLEMENTATION.md. There is no account-management portal/UI in this slice.

GET /v1/areas is available to both roles. Company administrators can POST /v1/area, PUT /v1/area/{id}, and DELETE /v1/area/{id} using P3 cookie mutation headers or bearer auth. Area CRUD controls/statistics/filter UIs remain later frontend slices. P4 does not add Tracking/Search/detail reads or other dashboard workflows. The existing frontend login/layout and its 11 Vitest/jsdom tests are regression checked; no new Playwright/E2E testing is claimed.

The evolving full backend suite runs 109 tests (53 unit / 56 PostgreSQL/Redis integration). Tests exercise empty/repeated migrations, downgrade/re-upgrade and schema drift; concurrent reference/address reuse and generated numbers; mapping edits/history/owner conflicts; immutable address/assignment and tenant FKs; weight/time boundaries; initial defaults/one Created; area role/tenant/HTTP contracts; and creation diagnostics/infrastructure failures. `scripts/verify-p4.sh` opts into all DB tests; normal verification skips those but checks lint/types/frontend/build/HTTP. The inherited one Starlette TestClient/httpx warning remains.

## P5 query APIs

No new migration or seed is needed; head remains 0003_creation_core. Rebuild/start and verify:

```sh
docker compose up --build --wait --wait-timeout 180
docker compose exec api alembic check
sh scripts/verify-p5.sh
sh scripts/verify.sh
python3 scripts/auth_smoke.py --credentials-file .local/development-users.json --check-areas --check-queries
```

After login, GET /v1/shipments defaults to due-today UTC. GET /v1/shipments/search?identifier=YOUR_REFERENCE searches all history; GET /v1/shipments/{stable_id} retrieves an authorized selected package. OpenAPI and [QUERY_IMPLEMENTATION.md](QUERY_IMPLEMENTATION.md) define filters, response DTOs, supported sorts and P6 navigation wiring. An empty development database correctly returns empty results; do not seed reference packages to make the page appear populated. Both seeded roles can read their own company's data. Query validation never writes creation ingestion errors.

P5 originally delivered full-result filtered Tracking metrics and rejected export mode. P8/P9 now supply carrier outcomes/selected POD URLs, P10 supplies My Day/area charts and P11 supplies durable exports/SSE. See the later sections for current startup and checks. No P5 browser or Playwright E2E was claimed.

## P6 UI

Open the existing frontend after login, then use Tracking, Search or Areas in the sidebar. Tracking begins with due-today UTC; Search spans history. There are no sample shipments seeded, so an empty local list is expected until authorized packages are created/imported. Area mutations require a company administrator. The existing private development credentials remain unchanged.

```sh
docker compose up --build --wait --wait-timeout 180
sh scripts/verify-p6.sh
python3 scripts/auth_smoke.py --credentials-file .local/development-users.json --check-areas --check-queries
```

P6 has no migration or dependency change. Compose additionally mounts frontend/tests read-only for synthetic UI test fixtures. The delivered routes, typed navigation, date picker, role/error/pending behavior and staged limitations are documented in [UI_IMPLEMENTATION.md](UI_IMPLEMENTATION.md). API schema remains 0003_creation_core. Frontend unit/component tests use Vitest/React Testing Library/jsdom; browser visual inspection of a temporary synthetic preview is separate from real HTTP/API tests and is not a Playwright E2E suite. No fixture packages or areas were seeded into the development database.

## Next slices
P1–P12 are complete, including the isolated real-backend browser/recovery journey, diagnostics and measured synthetic PostgreSQL baseline. Production deployment/capacity configuration remains separate. Actual executed results and limitations are recorded in [the task plan](../tasks/plan.md).

## DataGrip / local PostgreSQL access

Compose publishes PostgreSQL only on 127.0.0.1. Use a PostgreSQL data source with:

- Host: `127.0.0.1`
- Port: `5432`, or POSTGRES_PORT from your local environment
- User/database: POSTGRES_USER / POSTGRES_DB (`logistics` by default)
- Password: the original POSTGRES_PASSWORD from ignored `.env`
- SSL: disabled for this local development service

After changing port configuration, apply it with `docker compose up -d --wait postgres`. This recreates the container while preserving postgres_data and existing users/data. Never use `down --volumes` to fix connectivity. If port 5432 is occupied, set POSTGRES_PORT to another unused port in `.env` and use that same port in DataGrip. Changing POSTGRES_PASSWORD in `.env` does not reset the password stored in an existing database volume.


## P7 Paychex manifest intake

Use the existing database and private credentials. Do not overwrite .env or re-seed users when upgrading. Start the default stack, then explicitly migrate before enabling the optional worker:

```sh
docker compose up --build --wait --wait-timeout 180
docker compose exec api alembic upgrade head
docker compose exec api alembic check
mkdir -p sftp
chmod 700 sftp
# Set INTAKE_UID and INTAKE_GID in ignored .env to the outputs of:
id -u
id -g
docker compose --profile ingestion up --build -d --wait --wait-timeout 180 intake
docker compose --profile ingestion ps
```

INTAKE_UID/INTAKE_GID control the non-root worker's access to the local bind mount (container defaults 10001:10001). INGESTION_ROOT is /data/sftp inside the worker, mounted from ./sftp. Existing upload/archive files must be accessible to that configured owner. Only trusted operators should access this directory; worker-created directories are 0700 and captured files are 0600. Set producer permissions accordingly. All lifecycle directories must share a filesystem supporting hard links.

Head is now 0004_manifest_intake. No sources or account mappings are seeded. Register an actual authorized source explicitly, after configuring owner-provided service/account assignments as described in CREATION_IMPLEMENTATION.md:

```sh
docker compose --profile ingestion exec intake python -m app.ingestion.cli configure --company-slug paychex --poll-seconds 60
# Finalize a real authorized upload by renaming its .part file to .csv in:
# sftp/paychex/upload/
docker compose --profile ingestion exec intake python -m app.ingestion.cli status
docker compose --profile ingestion logs --tail=50 intake
```

Registration binds the existing active shipper to the Paychex adapter; it does not install sample accounts/packages. Re-running configure updates the independent poll interval/enabled flag; --disabled stops that source. The worker creates its source directories on the next tick. A one-off `python -m app.ingestion.cli once --root /data/sftp` inside the worker forces a directory scan while respecting payload retry backoff. Normal scanning defaults to 60 seconds per source.

Imports finish as completed/done, completed_with_errors/failed or failed/failed. PostgreSQL retains row outcomes and safe diagnostics. Archive failures retry independently; after fixing storage use `python -m app.ingestion.cli retry-archive --import-id UUID` inside the worker to reschedule only an exhausted archive. Check status as well as container health. The health heartbeat measures successful ticks, not successful business rows.

```sh
sh scripts/verify-p7.sh
python3 scripts/auth_smoke.py --credentials-file .local/development-users.json --check-areas --check-queries
```

The full suite uses synthetic manifests only in disposable databases/temporary directories. It does not import reference CSVs into the development tenant. No frontend feature/dependency change is required; existing Tracking/Search/detail display imported packages through the same APIs. [Implementation details](FILE_INGESTION_IMPLEMENTATION.md) cover receipt ordering, bounds, retry/archive recovery and remaining P8/P9/P11/P12 boundaries.


## P8 OnTrac events

Rebuild the default services and apply the additive migration before starting/recreating the optional worker; no re-seeding is required:

```sh
docker compose up --build -d --wait --wait-timeout 180
docker compose exec api alembic upgrade head
docker compose exec api alembic check
docker compose exec api alembic current
docker compose --profile ingestion up --build -d --wait --wait-timeout 180
sh scripts/verify-p8.sh
```

Head is 0005_carrier_events. Configure actual owner-provided service/account assignments before receiving carrier events. A trusted operator manually provisions an integrations row with company_id referencing OnTrac, adapter ontrac, active=true and only the SHA-256 verifier in apikey. Share the raw high-entropy key privately; never put it in committed examples, chat output, URLs or logs. No real integration or key is seeded/generated by the migration.

POST /v1/webhook/{integrationId} uses the raw numeric ID and X-API-Key, independently of dashboard login. OpenAPI and [the carrier implementation contract](CARRIER_INGESTION_IMPLEMENTATION.md) describe the exact DTO/acknowledgement, diagnostics, body limits and ordering. No outbound carrier submission is performed.

To enable actual authorized CSV intake under sftp/ontrac/upload, register the source explicitly:

```sh
docker compose --profile ingestion exec intake python -m app.ingestion.cli configure --company-slug ontrac --adapter ontrac_csv --poll-seconds 60
docker compose --profile ingestion exec intake python -m app.ingestion.cli status
```

The same worker handles both configured adapters, independently of their directory poll times. Carrier company/address/status/order columns never select tenants or edit original addresses. rows_completed includes accepted/duplicate/ignored rows; status now exposes duplicate/ignored subset counts. Unmatched rows are errors without delayed retries. Upload .part then rename .csv; archive behavior remains P7's durable lifecycle.

P8 added carrier time/signer and status/metrics/detail updates. P9 now validates image-bearing events and queues independent storage work, replacing the temporary P8 image gate. Unknown/duplicate events remain ignored; real S3 and a full real-backend browser E2E run remain separate. The development tenant is not populated with reference packages or real integration keys for verification.


## P9 POD preparation and storage

Use the existing private settings/users; no re-seeding, integration key or AWS provisioning is performed. Pillow 13.0.0 is frozen in the backend lockfile. Rebuild the default services, migrate explicitly, then enable/recreate both optional workers:

```sh
docker compose up --build -d --wait --wait-timeout 180 api frontend
docker compose exec api alembic upgrade head
docker compose exec api alembic check
docker compose exec api alembic current
docker compose --profile ingestion up --build -d --wait --wait-timeout 180
sh scripts/verify-p9.sh
```

Head is 0006_pod_images. The ingestion profile now includes intake and pod-worker. The image worker is non-root and needs only PostgreSQL, without the sftp mount or external storage credentials. It polls pending image work, records attempts before upload and reports a heartbeat independently of intake. Existing source/mapping/key setup remains operator-controlled; no real image/package/contact data is seeded.

Authenticated carrier webhook pod / CSV pod_image now accept actual JPEG/PNG base64: max 5,000,000 decoded bytes; width caps at 900 preserving aspect ratio/no upscale. Invalid images reject before event/field effects. Valid prepared bytes and image work commit with tracking; storage failures retry independently and never add an event or image row. Missing signer still leaves an incomplete delivery Undelivered. Detail uses existing pod_url and frontend image-failure handling.

```sh
docker compose --profile ingestion exec pod-worker python -m app.pod.cli status
docker compose --profile ingestion exec pod-worker python -m app.pod.cli once
# Explicit storage-only recovery after investigating the cause:
docker compose --profile ingestion exec pod-worker python -m app.pod.cli retry --image-id IMAGE_UUID
docker compose --profile ingestion logs --tail=50 pod-worker
```

The development adapter performs no actual upload and returns https://pod.invalid/... . This is deliberately not a downloadable image or proof of a real S3 object. Ready image metadata/URLs remain historical; pending/failed selected work returns no URL and never displays an older event's ready image. Prepared bytes remain restricted in PostgreSQL until readiness, with failed content retained for explicit retry. No HTTP endpoint exposes prepared content. See [POD implementation details](POD_IMPLEMENTATION.md) for exact bounds, event/receipt selection, retention and retry semantics. Real AWS, production resource/retention sizing and full real-backend browser E2E remain deferred/separate.

## P10 dashboard and verification
The root workspace is My Day. It uses the combined authenticated GET /v1/my-day; shipment-stats, exceptions-stats and area-stats are also available. No migration/dependency/seed change is required. See [DASHBOARD_IMPLEMENTATION.md](DASHBOARD_IMPLEMENTATION.md).

Run after starting the stack:
```sh
sh scripts/verify-p10.sh
python3 scripts/auth_smoke.py --credentials-file .local/development-users.json --check-areas --check-queries --check-day
```
The first command runs all opt-in PostgreSQL/Redis tests followed by standard lint, format, type, unit/UI, build and HTTP checks. Tests create disposable databases; they do not populate the development tenant. The second uses the existing private credentials without displaying passwords and verifies both roles against the live API.

If host port 8000 is occupied, set API_PORT=8001 in ignored .env and include http://localhost:8001 and http://127.0.0.1:8001 in AUTH_ALLOWED_ORIGINS while preserving existing origins. Recreate the API service. Compose reads .env; host smoke scripts instead require an explicit API_PORT=8001 prefix. The frontend proxy still uses api:8000 internally. During P10, port 8000 belonged to a separate fastapi-demo process, which was preserved; this checkout now runs at http://localhost:5173 with API/docs at http://localhost:8001/docs. Default example settings retain port 8000.

## P11 export startup and checks
P11 adds Alembic 0007_exports and the optional exports profile. Existing data and credentials are preserved. Create the download root before Compose mounts it; it is separate from intake upload/done/failed paths. Keep INTAKE_UID/INTAKE_GID in ignored .env equal to the host owner's numeric IDs (id -u / id -g), as for intake. The export worker runs with those IDs; the API adds that group for read access and mounts the download root read-only.

```sh
mkdir -p sftp/download
chmod 750 sftp/download
docker compose up --build -d --wait api frontend
docker compose exec -T api alembic upgrade head
docker compose --profile ingestion --profile exports up --build -d --wait --wait-timeout 180
```

The local checkout currently uses API_PORT=8001 in ignored .env. Run:
```sh
API_PORT=8001 sh scripts/verify-p11.sh
API_PORT=8001 python3 scripts/auth_smoke.py --credentials-file .local/development-users.json --check-areas --check-queries --check-day
python3 scripts/export_smoke.py --credentials-file .local/development-users.json
```

The export smoke creates one real job/file for each existing development user, verifies actual worker generation, proxy SSE, recovery, local CSV serving and requester isolation, then dismisses those notifications. It does not seed shipments/contacts/mappings. Files and job audit rows remain under the normal durable output policy. Unit/integration tests instead use disposable databases and temporary files. Standard profiles/startup without exports do not run the export worker; accepted jobs wait until it starts. A trusted one-off scan is docker compose --profile exports run --rm export-worker python -m app.exports.cli once. Host-only API and worker must share an explicit absolute EXPORT_ROOT pointing at sftp/download; container defaults are /data/exports.

Worker files are 0640/job directories 0750, with atomic publication before ready. Do not expose sftp/download as an unauthenticated static directory. API authentication still applies to copied local URLs. Interrupted .part files/failed output and retained completed artifacts need operator retention/quotas; no cleanup deletes existing files automatically. SSE uses a two-second durable-state check and replayable snapshots, with no Redis subscription requirement. See [EXPORT_IMPLEMENTATION.md](EXPORT_IMPLEMENTATION.md) for bounds and production/P12 limitations.

## P12 verification, diagnostics and recovery

```sh
API_PORT=8001 sh scripts/verify-p12.sh
docker compose exec -T api python -m app.ops.cli
```

The full application suite includes migration round trips/metadata, seed repeatability/concurrency, tenant/role/membership, event/file/image/job retries and a new manifest→carrier/POD→My Day→CSV recovery pipeline. Diagnostics is read-only and omits credentials, references/accounts/contact data, raw payloads and paths. It reports migration/timezone, import/archive states, image/export backlog/due work and error counts by code. Worker health is heartbeat health, not proof that every business row/job succeeded.

Real browser and service-outage checks use a separate Docker project with fake credentials and synthetic packages, never the development tenant. Start/stop, guards, the actual browser journey and PostgreSQL timing methodology/results are in [P12_VERIFICATION.md](P12_VERIFICATION.md). Do not combine compose.verification.yaml with compose.yaml. Its stop command removes only the dedicated test project volume. Run outage checks and benchmarks sequentially, without rebuilding images while either is active.

The development API now watches only /app/app and has --timeout-graceful-shutdown 5, avoiding test-file reloads and unbounded SSE draining. A deliberate application reload can close the stream; the browser reconnects/replays durable state. The lab disables source reload. Observable two-second heartbeat events plus a client watchdog renew silent streams after at least 15 seconds without a frame (checked every five seconds); background timer throttling can delay this. Existing focus/visible/manual recovery remains available. No ready artifact is regenerated for notification recovery.

P12 does not configure real AWS, retention/disk quotas, decoder isolation, production proxy/TLS/connection budgets, backups/restore drills or throughput SLAs. Measured local synthetic results are a baseline, not production certification. Evidence screenshots, recovery reports and downloaded synthetic CSV remain under ignored .local/p12; only the nonsecret synthetic performance report is included in docs/verification.
