# Implementation Plan

P1–P12 are complete and verified under owner authorization. Implement one small reviewed slice at a time.

| Task | Deliverable | Dependencies | Required verification |
|---|---|---|---|
| P1 — complete | Scaffold React/Vite, FastAPI, Compose, typed tooling and test harness | Baseline review and implementation authorization | Services boot; health checks; format/type/test commands |
| P2 — complete | Alembic company/user/role/action schema and editable development seed CLI | P1, SEED_DATA.md | Empty migration; seed twice; password hashes and role links; no real sample packages |
| P3 — complete | Shipper login and authenticated layout | P2 | Valid/invalid login; company isolation; administrator permissions |
| P4 — complete | Customer/address, mapping, area and shipment schema/services | P2 | Reference uniqueness; address reuse/immutability; generated-number collisions; defaults |
| P5 — complete | Tracking query/filters/pagination, Search and detail contracts | P3–P4 | Inclusive dates; selected-field Search; duplicate-number row navigation; tenant-safe detail |
| P6 — complete | Tracking/Search/detail UI and administrator area controls | P5 | Reference screenshots, accessibility, loading/error/empty states, role checks |
| P7 — complete | File lifecycle and Paychex manifest transformer/loader | P4 | Finalized files, content dedupe, partial→failed with valid rows retained, outage recovery |
| P8 — complete | Carrier webhook/OnTrac CSV, events and current-outcome reduction | P4, P7 domain services | Raw-ID/key auth, all mappings, repeated/out-of-order events, exact dedupe, unmatched errors |
| P9 — complete | POD validation/resize, dummy storage and independent image retry | P8 | JPEG/PNG/size limits, current-image selection, retry without new event |
| P10 — complete | My Day/filtered Tracking metrics and chart UI | P5, P8 | Independent metric fixtures, Void/return/POD rules, zero cases, placeholder categories |
| P11 — complete | Queued export, local CSV, SSE toast/recovery | P5, worker infrastructure | Full filters/no pagination, exact columns, file readiness, notification isolation/reconnect |
| P12 — complete | Integration/E2E verification, operational diagnostics and performance baseline | Prior slices | Tenant/retry tests, seed repeatability, measured queries, failure recovery |

For each task, record scope, schema/API/UI changes, test commands/results and limitations. Keep source imports and public endpoints synchronized with their contracts.

## Outside this plan
Elasticsearch, carrier dashboards, outbound carrier submission, detail map/star and real AWS setup remain deferred/planned. Do not add infrastructure for them merely because future interfaces are described.

## P1 results — 2026-10-24

Scope: React/Vite TypeScript startup page, FastAPI factory/configuration and typed health DTOs, four-service Compose stack, dependency lockfiles, environment examples, non-root application containers, persistent PostgreSQL volume, startup dependencies, test harness and local instructions. README/SPEC now distinguish delivered scaffolding from later domain implementation. No domain schema, migrations, seed data, login, shipment routes or worker behavior was added. No unresolved business rules arose in this slice; runtime/tool/probe choices are engineering decisions documented in DEVELOPMENT.md.

API additions: GET /health/live (200 independent of services) and GET /health/ready (200/503 with sanitized per-dependency status). Existing approved /v1 contracts are unchanged. UI: responsive static startup page and accessible health links through Vite's proxy. Database/session timezone is UTC. Redis remains disposable support. Queue selection is deferred to the worker slice.

Executed verification:

| Check | Actual result |
|---|---|
| `docker compose config --quiet` | Passed with locally configured ignored .env; password is required |
| `docker compose up --build --wait --wait-timeout 180` | Passed; frontend, API, PostgreSQL and Redis all healthy |
| `sh scripts/verify.sh` | Passed end to end against the running stack |
| Backend Ruff lint and format | Passed, four Python application/test files |
| Backend strict mypy | Passed, four files with Pydantic plugin |
| Backend pytest | 6 passed: liveness, all four readiness success/failure combinations, invalid non-UTC configuration |
| Frontend Prettier, ESLint and TypeScript | Passed |
| Frontend Vitest | 1 passed: startup page and accessible health links |
| Frontend production build | Passed with Vite 7.3.7 |
| HTTP smoke (`scripts/smoke.py`, called by verification) | Passed: frontend HTML, direct live/ready, proxied live/ready, real PostgreSQL and Redis probes |
| Stop Redis; call API health; restart Redis | live=200, ready=503 with only Redis unavailable; recovery succeeded |
| Stop PostgreSQL; call API health; restart PostgreSQL | live=200, ready=503 with only PostgreSQL unavailable; recovery succeeded |
| Post-outage proxy probes / Compose status | live/ready=200 through frontend proxy; all four services healthy |
| PostgreSQL `SHOW timezone`; public table count | UTC; 0 tables, as expected before P2 |
| Dependency audits | npm install after patched pins: 0 vulnerabilities; pip-audit against final backend environment: no known vulnerabilities |
| Ignored generated artifacts/config | .env, node_modules, dist and TypeScript build metadata confirmed ignored |

Initial dependency advisories and formatting/type issues were corrected before the final successful checks. Pytest emits one upstream Starlette warning that its httpx-based TestClient transport is deprecated; all tests pass. Host-only startup was documented but not executed (host Python is 3.9; the verified API runs Python 3.12 in Docker). Frontend host checks also passed before the final container verification. No visual browser/E2E, tenant/role, ingestion retry, migration or seed checks are claimed: those behaviors belong to later slices. Images pin release tags rather than immutable digests; this is a local development stack, not production deployment evidence. Audits were run using npm's advisory service and an ephemeral `uv tool run pip-audit` against /opt/venv/lib/python3.12/site-packages; pip-audit is not an application dependency.

Local services were left running at http://localhost:5173 and http://localhost:8000/docs. A runtime-generated local PostgreSQL password is kept only in ignored .env and the local database; it was not printed or committed. Stop with `docker compose down` to preserve the database volume. P2 remains the next separate task.

## P2 results — 2026-10-24

Scope: explicit online Alembic revision `0001_identity_catalogs`, SQLAlchemy Core metadata/UTC connections, editable transactional development seed CLI, shared Argon2id password helper, pinned Alembic/SQLAlchemy/Argon2 dependencies and lockfile, opt-in PostgreSQL test harness, updated environment examples/Compose mounts and development instructions. No new HTTP routes/DTOs or frontend flows were added; login and authorization remain P3. No unresolved business rules arose.

Schema: company (unique normalized slug, active, company_type constrained to carrier=1/shipper=2), user_role (unique normalized name), users (company and role FKs, unique company/email, nonempty password hash, active, aware created_at/updated_at), shipment_actions (unique normalized action). BIGINT identity keys, FK indexes and named constraints are engineering choices. Password is not unique. No legacy DDL was executed; no shipment/customer/mapping/integration tables were added. Migration contains no seed rows or password generation.

Seed: exactly Paychex and OnTrac, administrator/user roles, seven approved actions and two active Paychex users with correct roles. Natural keys resolve actual IDs. Repeated/concurrent runs do not duplicate records, reset passwords/settings or alter existing user roles/activation. A transaction advisory lock serializes seed runs; unique constraints also protect identities. Declarations can be extended without changing core logic. APP_ENV must explicitly select development; production/default refuses. New passwords are generated at runtime and stored as salted Argon2id hashes; terminal output is interactive only, or credentials are written to a newly created private 0600 file. Prepared files are flushed before commit; write failure rolls back, while a prepared file is retained after a possible commit failure for recovery. No credentials were printed in tool output/chat or committed.

Executed verification:

| Check | Actual result |
|---|---|
| `docker compose up --build --wait --wait-timeout 180` | Passed with P2 dependencies and migration mounts; all four services healthy |
| Ruff lint/format, strict mypy including migrations | Passed, 16 Python files |
| `sh scripts/verify-p2.sh` | 23 passed, including nine real PostgreSQL integration tests |
| Empty migration, repeat upgrade, downgrade/base, re-upgrade | Passed only in disposable test databases; migrations create no data |
| `alembic check` / metadata comparison | Passed with no upgrade operations/drift |
| Seed twice and concurrent seeds | Passed; one set of records and initial credentials only, existing hashes unchanged |
| Password verification | Separate salted Argon2id hashes; correct passwords verify, wrong/malformed hashes rejected |
| Identity/FKs/catalog constraints | Duplicate identities and dangling company/role references rejected; same email allowed across companies, repeated password hash allowed |
| Preservation/extensibility | Manually edited company/user state and promoted roles preserved; extra declarations seeded without core changes |
| Seed failure/CLI guards | Invalid declarations rejected, failed credential sink rolls back, production and noninteractive console refused, file overwrite/symlink refused, new file mode 0600, unmigrated CLI error sanitized |
| `sh scripts/verify.sh` regression | Passed: backend 14 passed / 9 opt-in DB tests skipped; frontend formatting/lint/type, 1 UI test, production build, direct/proxied HTTP smoke |
| Local development `alembic upgrade head`, `alembic check`, `alembic current` | Applied successfully; current 0001_identity_catalogs (head), no drift |
| Actual local seed executed twice with separate private destinations | First run created 2 companies / 2 roles / 7 actions / 2 users; rerun created nothing and returned no new credentials |
| Local seed inspection | Both passwords verified internally without display; correct table/count boundary, no sample shipments/contacts/accounts/keys |
| Backend dependency audit | pip-audit against final installed environment: no known vulnerabilities |
| Final `docker compose build api` | Passed with final source and frozen lockfile |
| Final Compose / database cleanup | Configuration valid; all four services healthy; zero p2_test_* databases remain |
| Private credential copy | `.local/development-users.json` validated as 0600 with two new-user credentials and confirmed Git-ignored |

Initial test-fixture URL/row handling and type/format issues were corrected before successful checks; failed-fixture disposable databases were removed. A premature private-file copy was refreshed after seed completion, then validated; no credential contents were displayed. The existing upstream Starlette TestClient/httpx deprecation warning remains (one warning). Host-only execution/offline SQL generation, actual login and API role enforcement are not claimed: host-only commands were documented, Alembic is online-only, and P3 will use the shared password verifier for the real login flow. Timestamps initialize in PostgreSQL; later user mutations must maintain updated_at. No seed password reset/override command is included.

Local services remain running. Initial development credentials are preserved in ignored `.local/development-users.json` (directory mode 0700, file 0600) and are not checked into source control. Source copies inside the current container are ephemeral. P3 is the next separate task.

## P3 results — 2026-10-24

Scope: approved POST /v1/login; typed GET /v1/session and POST /v1/logout engineering interfaces; signed PostgreSQL-backed sessions; HttpOnly cookie/bearer authentication; live membership/role verification; shared administrator dependency; Redis login throttling; bounded/sanitized login input; accessible login form and authenticated company/role layout. No shipment/customer/mapping/area workflows, SSE endpoint, credential reset, refresh/MFA/recovery flow or extra tenant seed data was added. Security/session details were routine engineering choices, recorded in docs/AUTHENTICATION.md and OpenAPI; no business questions were reopened.

Schema: explicit revision 0002_auth_sessions adds auth_sessions digest PK, user/company association, aware creation/expiry, expiry/hash checks, expiry/membership indexes and composite membership FK backed by a users(id,company_id) unique key. Only a random-ID digest is stored; usable signed tokens and plaintext passwords are not persisted in PostgreSQL. P2's existing users/passwords remain intact. Migrations never seed or generate passwords.

Security: tokens are signed using itsdangerous/HMAC-SHA256, expire after eight hours and resolve current active shipper membership/role from PostgreSQL for each protected request. Logout revokes the current session. The browser uses host-only HttpOnly/SameSite=Strict cookies, Secure in production, and does not store tokens in local/session storage or URLs. Cookie mutations require the application header and allowed Origin when supplied; JSON login plus same-origin transport rejects cross-site form/preflight access. Startup requires a strong signing secret and production HTTPS origins. Redis atomically limits normalized identity/source-IP attempts using private hashed keys; outages fail login closed. User password checks reuse P2 Argon2id hashing. Unknown/inactive/carrier identities share the same 401 response; passwords and dependency errors are not reflected in responses. Administrator enforcement is exercised through test-only protected routes; production area mutations await their own slice.

UI: labeled Email/Password/Company slug fields, password masking, native validation, disabled pending submission, focused errors, throttling/network feedback, session restore on load/focus, visible expiry, logout/retry and a responsive company-scoped layout. Identity and role come from /v1/session, not editable client state. Stale restore responses cannot reopen a signed-out workspace. Shipment features are honestly marked as future work with no invented metrics or working area controls.

Executed verification:

| Check | Actual result |
|---|---|
| Final `docker compose up --build --wait --wait-timeout 180` | Passed; all four services healthy |
| Final `sh scripts/verify.sh` | Passed: backend 16 passed / 37 opt-in skipped; frontend 11 passed, format/lint/type/build and HTTP smoke |
| P3 backend suite (`sh scripts/verify-p3.sh`) | 53 passed; 37 real PostgreSQL/Redis integration tests, 16 unit tests |
| Existing migration/seed regression | Empty/repeated upgrades, downgrade/re-upgrade, metadata check, seed repeat/concurrency and credential guards passed against disposable databases |
| Authentication coverage | Both seeded roles; invalid/missing input and generic failure; disabled user/company, carrier/unsupported role; overlapping tenant identities; company/role override attempts; live role/membership rechecks |
| Token/cookie coverage | Missing/tampered/expired/revoked/rotated tokens, independent DB expiry, cookie attributes, cookie/bearer precedence, CSRF/origin checks, logout revocation, no query-token authentication |
| Infrastructure/contract coverage | Real Redis limits and key TTL/privacy/cleanup; Redis/database errors fail closed with sanitized 503; bounded login bodies; OpenAPI response/security consistency |
| Ruff lint/format and strict mypy | Passed, 25 Python files including migrations |
| Frontend Prettier/ESLint/TypeScript | Passed |
| Frontend Vitest | 11 passed: input/accessibility, login/restore/logout, role UI, errors/loading/duplicate submits, offline retry, failed logout, expiry and stale-response protection |
| Frontend production build | Passed |
| Local populated P2 migration to P3 | Applied 0002_auth_sessions successfully, no Alembic metadata drift; existing seeded credentials still authenticate |
| Live `scripts/auth_smoke.py --credentials-file .local/development-users.json` | Both real local roles passed proxy login, cookie restoration, direct bearer access and logout revocation without printing credentials |
| Browser visual verification | Default login layout inspected; at 390px, page/scroll width both 390 and submit width 342 (no horizontal overflow); viewport override reset |
| Backend dependency audit | No known vulnerabilities in final installed dependency set |
| Disposable database cleanup | Zero p2_test_* databases remain |

Initial fixture/type issues were corrected before the passing checks. A stale frontend image copy of vite.config.ts was identified by the full container format check and rebuilt. The inherited Starlette TestClient/httpx deprecation warning remains (one warning). Browser inspection covers login appearance/responsiveness; full authenticated browser E2E remains P12 work, while automated frontend tests and live HTTP checks verify the authentication lifecycle. No production capacity/security certification is claimed: trusted proxy/IP configuration, rate-limit tuning and expired-session retention require deployment configuration. Cookies support future same-origin SSE, but no SSE route is implemented yet. Actual shipment/area tenant predicates and mutations remain their planned slices.

The generated AUTH_SECRET is stored only in ignored local .env; the previously seeded credentials remain in private ignored .local/development-users.json. No passwords were reset or additional real tenant records seeded. Local services remain available at http://localhost:5173 and http://localhost:8000/docs. P4 is the next separate task.

## P4 results — 2026-10-24

Scope: Alembic 0003_creation_core, tenant-safe customer/address/validation linkage, current service mappings with retained carrier/account ownership, area persistence/CRUD services, shipment creation and one-time Created history, collision-safe generated-number reservations, deadline/weight normalization and separately persisted creation diagnostics. Finalized typed POST /v1/shipments (201 new / 200 existing) and approved GET /v1/areas plus POST/PUT/DELETE area APIs with P3 authentication/role/CSRF enforcement. No account-management UI, shipment query/dashboard UI, carrier/file ingestion, area statistics, POD or export behavior was added. Existing frontend code remains P3's login/layout.

Owner clarification D49: existing-reference create API requests return the existing package unchanged; edits remain in authorized ingestion flows. Recorded in DECISIONS.md, SHIPMENT_CREATION.md and the implementation contract. Valid retries preserve addresses, assignment, number, deadline, optional creation values and Created event. Original service/account inputs remain valid after mapping edits; mismatched/unknown accounts are still rejected. No other business rules were reopened.

Schema: nine new tables (customers_validated, customers, carrier_accounts, account_mapping, area, generated_shipment_numbers, shipments, shipment_events, ingestion_errors), a receipt-order sequence and immutable-field/number-write guards. Reference uniqueness is tenant scoped; source shipment numbers can repeat. Customer reuse is exact after trimming, includes tenant and NULL address_two equality, and never overwrites shared metadata. Composite FKs enforce customer/validation/route ownership. Mapping cardinality permits same-owner multi-service accounts and same account strings under different carriers, while retaining old ownership for historical package matching. Database triggers preserve original address and shipment assignment/identity/pointers. UTC deadline/date consistency and exact event triples are constrained in PostgreSQL.

Creation: required string identifiers/ZIP stay strings; optional blanks become NULL on initial creation. Decimal weights round HALF_UP to two places with finite/nonnegative/999.99 boundaries. Initial missing deadline uses PostgreSQL processing date's next weekday at 17:00 UTC; supplied dates/offsets/local zones validate without weekend shifting or DST guessing. New shipments have NULL route/order_date/POD/delivery/notes, and one Created at the initial processing instant. Invalid business input rolls back address/reservation/shipment/event effects; a separate scoped API error record stores reason/account/reference/user/time without raw address/contact payloads. Diagnostic storage failure returns 503.

Executed verification:

| Check | Actual result |
|---|---|
| `sh scripts/verify-p4.sh` | 109 passed: 53 unit and 56 PostgreSQL/Redis integration tests, including prior slices |
| Ruff lint/format and strict mypy | Passed, 37 Python files including migrations |
| `sh scripts/verify.sh` | Passed: 53 unit / 56 opt-in skipped, frontend checks, 11 frontend tests, production build and HTTP smoke |
| Empty/repeated migration, downgrade/re-upgrade, metadata comparison | Passed in disposable databases; no Alembic drift |
| Concurrent creation/reuse | One shipment/address/Created for simultaneous same-reference calls; shared tenant address reuse for distinct references |
| Reference/tenant identity | Distinct references remain distinct despite repeated numbers; same reference/address across shippers stays isolated; strict identifier/ZIP preservation |
| D49 retries | Entire creation acknowledgement unchanged despite replacement fields; no new address, default, generated reservation or Created |
| Generated numbers | 15-character format, supplied/current/reserved collision detection, bounded exhaustion rollback, cross-tenant generation race; later supplied duplicates allowed |
| Mapping behavior | Multi-service sharing, same account across carriers, future-only mapping edits, historical owner lookup and concurrent conflicting-owner rejection |
| Integrity | Original address/assignment/pointers immutable; cross-tenant customer/validation/area FKs rejected; UTC date mismatch and exact duplicate events rejected |
| Deadline/weight tests | NULL/zero/rounding/overflow/nonfinite inputs; UTC midnight/year/weekend defaults; offset/missing zone/summer/winter/DST ambiguity/nonexistence/invalid zone and atomic invalid-input rollback |
| Area services/APIs | Normalization including Unicode, alphabetical shared reads, duplicate/create/rename no-op, soft-delete/repeat/restore, link preservation, deleted edit rejection, tenant/role/forged-role checks, exact HTTP responses |
| API/error contracts | 201/200 creation, exact missing-account message, rejected spoofed fields and bad inputs with scoped diagnostics, CSRF/auth checks, sanitized DB/diagnostic failures, typed OpenAPI responses |
| Final `docker compose up --build --wait --wait-timeout 180` | Passed; all four services healthy |
| Local explicit migration/check/current | Applied 0003_creation_core to the populated P3 database; no new upgrade operations detected |
| Live `auth_smoke.py --credentials-file .local/development-users.json --check-areas` | Both existing seeded roles passed protected area reads plus proxy login, cookie restore, bearer access and revocation; credentials were read internally, never printed |
| Local business table inspection | All nine P4 tables empty: no package/contact/account/mapping/area data was seeded |
| Final cleanup/config | Compose config valid; all services healthy; zero disposable p2_test_* databases remain |

Implementation notes and limits: CREATION_IMPLEMENTATION.md records DTOs, input limits, physical invariants, manual mapping setup and retry semantics. No dependency versions changed in P4. The inherited Starlette TestClient/httpx deprecation warning remains (one warning). Migration generation initially hit a read-only Compose mount/default-dialect renderer issue; the migration was then rendered into the workspace with the PostgreSQL dialect, reviewed and verified against real PostgreSQL. Initial lint/type/test-fixture issues were corrected before passing checks. No documentation-only test is counted as an application test.

Frontend verification was the existing Vitest/React Testing Library/jsdom suite plus build; no new UI/browser/Playwright flow was implemented or claimed. Area controls and Tracking/Search/detail UI remain their planned slices. Carrier-only route assignment, accepted-event receipt ordering/reduction and ingestion error/import lifecycle still belong to P7/P8; P4 allocates only synchronous Created order and does not treat worker completion as acceptance order. The global shipment-number write lock is a correctness-first baseline requiring later throughput measurement. No external services, real accounts, integration keys, shipments or historical sample contacts were provisioned.

Development services remain running, with existing credentials unchanged. P5 is the next separate task.

## P5 results — 2026-10-24

Scope: typed GET /v1/shipments Tracking filters/pagination/sorting with full-filter counts/OTP, GET /v1/shipments/search exact selected-field history lookup, GET /v1/shipments/{shipment_id} authorized stable-ID detail, and documented P6 typed/selected-row navigation. PostgreSQL supplies recipient/area/carrier joins, current terminal/latest-action projections and consistent repeatable-read snapshots. No migration, dependencies, seed changes or frontend feature work. Existing creation validation/diagnostic handlers now explicitly apply only to POST so invalid GET filters never create ingestion errors. Shared synthetic fixture helpers support both creation and query tests.

Engineering interface choices are recorded in docs/QUERY_IMPLEMENTATION.md and OpenAPI: strict date strings; due_date/order_date/deliver_time/created_at filters; default 10/max 100 rows; page >=1; empty out-of-range pages; bounded repeated area IDs; validated sort whitelist with NULLs last and stable numeric ID ties; unknown/repeated singleton query rejection; string stable IDs; seven Search display columns plus navigation ID. No unresolved business rules arose. Read responses carry no-store; foreign/missing detail share the same 404; SQL failures are sanitized 503. Both roles remain scoped to verified active shipper membership.

Tracking metrics are implemented here because the Tracking list contract requires full-filter results. My Day/area statistics/chart UI remain P10. Status uses Void priority, selected Returned override, final delivery time/nonempty POD name; exception reduction selects the latest overall action before filtering, including events outside the report day. OTP excludes Void, applies non-Void empty/no-delivery cases and strict earlier-than deadline with two-decimal rounding. Detail preserves original addresses, incomplete/returned delivery time, repeated history and actual local UTC offsets.

Executed verification:

| Check | Actual result |
|---|---|
| `sh scripts/verify-p5.sh` | 134 passed: 70 unit and 64 real PostgreSQL/Redis integration tests, including all P1–P4 regressions |
| New P5 coverage | 25 tests: malformed/one-sided/reversed dates, inclusive date/timestamp boundaries and microseconds, default DB UTC day, max date, filters/area OR, active/deleted/foreign areas, stable paging/sorts and full-filter metrics |
| Status/exception/detail coverage | Void/return/incomplete POD, out-of-order and equal-time receipt ties, latest non-exception suppression, repeated-event histories without multiplied counts, deadline equality/66.67 rounding, empty/all-Void/no-delivery OTP, original addresses, DST/UTC serialization |
| Search/ownership coverage | Selected namespace only, trim/case/leading zeroes, old/Void lookups, duplicate-number pages and selected stable detail, missing/foreign IDs, forged/inactive membership, both authenticated roles and HTTP cross-tenant denial |
| API/error consistency | OpenAPI security/DTOs, numeric pagination, no-store, bounded/unknown/repeated query rejection, repeated area query transport, invalid queries produce no ingestion diagnostics, sanitized database failure |
| `sh scripts/verify.sh` | Passed: backend 70 passed / 64 opt-in skipped; Ruff lint/format; strict mypy 43 Python files; frontend Prettier/ESLint/TypeScript; 11 Vitest tests; production build; HTTP health/proxy smoke |
| Rebuilt Compose stack | All four services healthy after `docker compose up --build --wait --wait-timeout 180` |
| Live seeded-role query smoke | Both roles passed proxied Tracking pagination/metrics and exact reference Search, plus area reads and complete cookie/bearer login/logout smoke; no credentials displayed |
| Local schema/data cleanup | Alembic reports no drift, head remains 0003_creation_core; shipments/customers/account_mapping each have zero real development rows; zero p2_test_* databases remain |

One initial synthetic history fixture had its real processing-time Created event newer than the seeded historical return, correctly suppressing the Returned exception. The fixture was made chronologically explicit before the final passing suite. Import/type/format cleanup was completed before verification. The inherited single Starlette TestClient/httpx deprecation warning remains.

Limitations: current delivery-field writes remain P8's ingestion service; P5 reads their canonical values. Detail pod_url is honestly null until P9 provides image metadata/storage and verifies late-completion selection; no image processing/readiness claim. export=1 returns 422 until P11 can durably accept work. Tracking/Search/detail/area-control UI remains P6; no browser/Playwright/E2E work is claimed for this backend slice. No production-scale query benchmark is claimed (P12). No tenant shipment/contact/account samples were added to the actual development database.

## P6 results

Scope: React Tracking/Search/detail and shared area screens, client History API navigation, typed/runtime-validated P4/P5 DTOs, abortable reads with stale-response protection, extended same-origin cookie/CSRF transport for area PUT/DELETE, responsive styling and keyboard-accessible controls. No new dependency, backend route, database migration or seed change. Compose mounts frontend/tests read-only for synthetic fixtures. Exact engineering routes/navigation/filter behavior are in docs/UI_IMPLEMENTATION.md; no genuinely unresolved business rules arose.

Tracking: default database UTC date, staged Sunday-first two-month date picker, UTC presets, inclusive paired bounds, Apply/Cancel, arrows/Escape/focus containment and restoration; exact account text, status/exception single selects, repeated active-area OR, explicit reset and selected unavailable-area handling. Committed filters/sorts reset page 1. Table uses supported server sorts, frontend column selection, visible status text/dots, preserved string IDs/ZIP and available incomplete-delivery time. Total/Undelivered/OTP come from the full filtered API population. Missing Driver/account sort was not invented outside the P5 DTO/sort contract.

Search/detail: default reference and selected-field-only history lookup, trimmed exact identifiers, safe exact no-match text, singleton redirect and seven-column paginated multiple-match selector. Selected row carries stable identity and namespace through /tracking/detail/{identifier}; direct ambiguous URLs use the same selection flow. Escaped separators and dot-only identifiers survive URL normalization with explicit encoding context. Detail renders original addresses, service/carrier/reference/weight, current status including Void, repeated ordered events and actual recipient offsets, independent time/signer and one nullable POD image with failure handling. No map/star/edit/outbound actions.

Areas: company-shared reads, administrator-only Add/Enable/edit/delete, edit controls off on remount/reload, focused name/confirmation dialogs, duplicate/no-op/restore API results, exact Area deleted response, retryable errors, duplicate-submit guard and pending controls. Success refetches active options and invalidates Tracking reads; role/company changes discard old data and pending operations. My Day/area statistics refresh remains P10 because those APIs/cards do not exist yet.

Executed verification:

| Check | Actual result |
|---|---|
| Full backend suite from `sh scripts/verify-p6.sh` | 134 passed (70 unit + 64 PostgreSQL/Redis integration); includes tenant/role/area mutation, query and migration regressions |
| Final frontend Vitest/RTL/jsdom suite | 36 passed: existing 11 auth tests, 17 workspace tests and 8 UTC date tests |
| UI query coverage | Loading/error/retry/empty/malformed DTOs, full-result metrics, exact account/area/status query parameters, server sorting/page reset/size, local columns, inclusive date Apply/Cancel/presets and year/leap cases |
| Navigation/detail coverage | Namespace-only Search, seven columns, duplicate-number selected ID, singleton/no-match text, safe HTML/URL/dot escaping, direct ambiguity, history navigation, original addresses, Void/incomplete time, repeated events, offsets and failed POD image |
| Role/lifecycle coverage | User read-only area UI, administrator create/restore/edit/no-op/delete transport, Enable reset, duplicate/error/pending guards, cookie mutation header, focus trapping/Escape/restore, protected 401 clearing, verified company switch and late-response isolation |
| Final standard `sh scripts/verify.sh` | Ruff lint/format, strict mypy (43 Python files), backend 70 passed / 64 opt-in skipped, frontend Prettier/ESLint/TypeScript, 36 frontend tests, production build and real direct/proxied health smoke passed |
| Browser visual/interaction inspection | Desktop Tracking table/metrics, two-column detail, two-month picker, multiple-match Search and administrator Enable/edit modal inspected using synthetic preview responses |
| Responsive browser measurements | At 390px: document width 390, sidebar width 390, detail single column; Tracking table scrolls within 356px region (1054px content); date dialog/content both 358px without page overflow; viewport override reset |
| Live seeded-role HTTP smoke | Both unchanged local roles passed real proxy login, cookie/bearer session, area reads, Tracking/Search reads and logout/revocation; no credentials displayed |
| Final rebuilt Compose | All four services healthy; frontend production build succeeds with frozen existing dependencies |
| Local schema/data/cleanup | Head remains 0003_creation_core; shipments/customers/area/account_mapping each contain zero development business rows; zero disposable test databases; temporary preview stopped and tab closed |

The macOS permission/app restart interrupted verification but preserved the workspace changes. Resumed from saved state. Initial TypeScript/import and test selector/timing issues were fixed; modal focus enumeration was made DOM-order based, and browser inspection caught/fixed a mobile sidebar cascade issue. Final checks passed. One inherited upstream Starlette TestClient/httpx deprecation warning remains.

Browser evidence used a temporary loopback static-build preview with synthetic API responses, not seeded database records. Inspection used the app's computer-use browser API and its Playwright-style locators; no installed Playwright E2E suite is claimed. Real API/security checks ran separately through PostgreSQL tests and credential-safe HTTP smoke. Ignored screenshots are in .local/p6-review. Full real-backend browser shipment E2E stays P12.

POD readiness/storage remains P9 (real pod_url still null), My Day/area charts remain P10 and export/SSE/download remains P11; no fabricated statistics/images/acceptance controls were added. Existing PostgreSQL users/passwords are unchanged, no external services/accounts were provisioned, and no source reference shipment/contact samples were seeded. Development services remain at http://localhost:5173 and http://localhost:8000/docs. P7 is the next separate task.


## P7 results — 2026-10-25

Scope: additive Alembic 0004_manifest_intake, trusted source configuration, a PostgreSQL-backed scheduler/worker, restricted CSV snapshots, durable import/row checkpoints, source-scoped content dedupe, independent archive recovery, exact Paychex transformer/loader and shared creation/update services. Compose adds the optional ingestion profile with a non-root worker, local sftp bind mount and heartbeat health check. No new public API, UI or dependency; no carrier webhook/event ingestion, POD, exports or SSE. README/SPEC, architecture/data model, development startup and FILE_INGESTION_IMPLEMENTATION.md now describe the delivered boundary.

Owner clarification D50 remains authoritative: Paychex service description and order date populate only on first creation and are preserved on updates. Existing manifests can correct only nonempty number/notes/deadline while retaining addresses, assignment, reference and one Created event. Missing fields preserve stored values. Original service selectors remain authorized after future-only mapping edits. No completed business decision was reopened.

Engineering choices: PostgreSQL durable queue/checkpoints with per-source session advisory locks; independently configurable 60-second directory polling; initial-claim UTC archive date and immutable snapshot; per-logical-row receipt sequence committed before business execution; per-field last-valid-receipt guards shared with synchronous creation. Five payload/capture attempts and five independent archive attempts use bounded backoff. Invalid structure/business rows do not auto-replay. Archive hard links are atomic/no-overwrite and recover both link and unlink checkpoint gaps; exhausted capture preserves the complete original rather than a partial snapshot. One broken source does not starve another. Limits and operator repair procedures are documented separately from business rules.

Executed verification:

| Check | Actual result |
|---|---|
| Final `sh scripts/verify-p7.sh` | Passed: 173 backend tests (87 unit + 86 real PostgreSQL/Redis integration), all prior-slice regressions included |
| P7 focused tests | 39 passed: 17 manifest/file unit cases and 22 PostgreSQL intake cases |
| File lifecycle | .part finalization; BOM/quoted newline/width/structure checks; source isolation/configurable polling; overlapping claims; same-source renamed dedupe; changed content/new import; partial valid-row retention; UTC archive dates and collisions |
| Manifest/domain behavior | Exact string mappings/ZIP/notes; generated number/default deadline; source order date; D50 preservation; historical assignment; immutable address/customer reuse; invalid-row atomicity; recipient timezone/DST rejection |
| Recovery/ordering | Row checkpoint crash/resume; older accepted retry cannot replace newer field values; independent per-field guards; post-claim and pre/post-archive-unlink crashes; exhausted payload/archive backoff; complete oversized/unreadable/partial-capture raw archive; broken-source isolation |
| Ruff / formatting / strict mypy | Passed; 57 Python files checked |
| Standard verification in the P7 script | Backend 87 passed / 86 opt-in skipped; frontend Prettier/ESLint/TypeScript, 36 Vitest/RTL/jsdom tests, production build and direct/proxied HTTP readiness smoke passed |
| Migration consistency | Empty/repeated upgrade, downgrade/re-upgrade and metadata comparison passed in disposable databases; explicit local upgrade applied 0004_manifest_intake; `alembic check` found no drift and current reports head |
| Final Compose build/start | `docker compose --profile ingestion up --build -d --wait --wait-timeout 180` passed; PostgreSQL, Redis, API, frontend and intake all healthy |
| Rebuilt intake CLI | One-off scan succeeded, status returned [] with no sources/imports configured; local mount ownership set through ignored .env without changing existing secrets |
| Live seeded-role HTTP smoke | Both existing roles passed login/cookie/bearer/revocation, area reads, Tracking metrics/pagination and exact Search; no credentials displayed |
| Local data and cleanup | ingestion_source/imports/rows, shipments, customers, area and account_mapping each contain zero rows; no reference data imported; zero disposable p2_test_* databases remain |

The resumed work first restored missing test imports. Review then found and fixed broken-source starvation and partial-capture archive truncation; focused regressions and the final full suite passed after those fixes. One inherited Starlette TestClient/httpx deprecation warning remains. No documentation-only test is counted as an application test, and no new browser/Playwright E2E run is claimed.

Operational limits: finalized producer files must remain immutable; lifecycle paths must share a filesystem supporting hard links. Parse bounds are 20,000,000 bytes/20,000 rows/65,536 characters per field; streaming the complete raw failed input still requires disk capacity. Persisted failures require operator inspection; the archive-only retry command does not replay package effects. No production throughput, disk quota, retention or performance certification is claimed. Worker health measures successful source/database ticks, not successful import outcomes. Actual sources and owner-provided account mappings must be configured explicitly; none were created in the development tenant. PostgreSQL users/passwords remain unchanged. P8 carrier events, P9 POD, P10 My Day/area charts, P11 export/SSE and P12 real-backend browser/performance verification remain separate.

Local services remain at http://localhost:5173 and http://localhost:8000/docs. P8 is the next separate task.


## P8 results — 2026-10-27

Scope: additive Alembic 0005_carrier_events, integrations API-key verifiers, durable synchronous webhook receipt/outcome records, raw-ID POST /v1/webhook/{integrationId}, exact OnTrac transformer/loader, carrier CSV dispatch through P7 intake, carrier-scoped diagnostics and ignored/duplicate counters. Shared transactions enforce carrier/account/shipper/reference matching, immutable assignment/addresses, exact event dedupe, event-time/receipt ordering, last-valid-receipt field guards and delivery-time maintenance. Existing P5/P6 queries/UI consume the same DTOs and immediately reflect accepted history/status/routes/deadlines/metrics. No frontend feature, dependency or external service was added.

All existing business decisions remain authoritative, including D50 creation-only manifest service/order fields. No genuinely unresolved business rule arose. Engineering acknowledgement/body/error/status choices are documented in CARRIER_INGESTION_IMPLEMENTATION.md and OpenAPI, along with trusted integration/source setup in DEVELOPMENT.md. README/SPEC, API, architecture/data model and file implementation documents now distinguish delivered P8 from P9 images and later work.

Authentication: an active carrier integration with a live lowercase SHA-256 verifier authenticates the routed raw numeric ID via exactly one X-API-Key header. Missing/wrong/cross-integration keys, invalid IDs, shipper integrations and disabled companies/integrations return exact 401 {"message":"Invalid API key"}. Verification happens before JSON reading and again in the business transaction, including rotation during a slow upload. User sessions do not authorize carrier ingress. API keys, raw JSON and base64 are not logged or retained in receipt bodies. Transport parsing rejects malformed/repeated-key/non-object/non-JSON-constant input and bounds streamed requests at 7,000,000 bytes.

Accepted/duplicate/ignored webhooks return 200 only after a durable synchronous outcome; authenticated business errors commit a rejected receipt plus sanitized PostgreSQL diagnostic and return 400. Infrastructure/image-stage unavailability returns 503 without false acknowledgement. Requests keep a digest and receipt/source correlation, not a full raw payload. CSV keeps restricted source snapshots and atomic per-row outcomes/counters using P7's partial-file/archive/dedupe/retry lifecycle. Carrier errors record the trusted carrier and resolved shipper where available; they never mistake the carrier source company for the shipper tenant. Unmatched rows are never automatically retried after a package appears.

Event behavior: exact/canonical duplicates ignore every associated mutation; unknown codes ignore optional fields without creating business data. Original source time and normalization zone stabilize accepted retries after recipient validation changes. Distinct events preserve history; latest delivered/returned uses event time then receipt order, independent of execution. Only delivered actions supply actual delivery time; return retains history/time/name while status becomes Undelivered; nonterminals do not undo established delivery. Signer/notes/number/deadline/route use per-field last-receipt guards, missing values preserve, stale routes create no unused areas and deleted areas are reused without restoration. Source times/explicit offsets/UTC fallback/DST rejection share existing normalization rules.

Executed verification:

| Check | Actual result |
|---|---|
| Final `sh scripts/verify-p8.sh` | Passed: 225 backend tests, comprising 111 unit and 114 real PostgreSQL/Redis integration tests; all prior slices included |
| New P8 application coverage | 52 cases passed within the full suite: 24 transformer/parser unit cases and 28 carrier integration cases |
| Authentication/API | All six CSV/seven webhook mappings; exact 401 before malformed JSON; raw/unknown IDs, missing/wrong/duplicate/cross keys, inactive/type boundaries, live replacement and replacement while reading; request/media limits, strict JSON, typed OpenAPI/error schemas and sanitized SQL failure |
| Ownership/business integrity | Repeated references across shippers, carrier/account isolation, leading-zero strings, reference priority over repeated numbers, historical accounts after mapping edits, inactive shipper rejection, original address/assignment preservation and no unmatched shipment/event/area creation |
| Dedupe/history/outcome | Changed duplicate auxiliaries ignored, canonical/source-time normalization stability, concurrent exact duplicates, repeat actions/times, missing signer/time preservation, Delivered/Returned/Delivered, terminal ties, late older events, nonterminal behavior and Void override |
| Receipt fields/areas/metrics | Reverse execution preserves newer name/notes/deadline/route; number guards retain P7 coverage; per-field behavior across manifest/CSV; normalized deleted-area reuse without restoration; tenant-separated same route names; strict-deadline and correction-driven Tracking metrics |
| Carrier file recovery | Final rename, multi-shipper rows, unknown/duplicate subsets, partial valid rows retained, unmatched diagnostics/no delayed matching, renamed-file dedupe, row crash/resume with stable receipt sequence, infrastructure retry preserving newer manifest fields and image-stage row rejection with later valid rows retained |
| Ruff / formatting / strict mypy | Passed across 68 Python files |
| Standard verification in P8 script | Backend 111 passed / 114 opt-in skipped; frontend Prettier/ESLint/TypeScript, 36 Vitest/RTL/jsdom tests, production build and direct/proxied health smoke passed |
| Final OpenAPI amendment | Focused real-DB API/error/limit test plus lint/format/types passed after documenting typed 413/415 responses; runtime business behavior unchanged |
| Migration consistency | Empty/repeated upgrade, downgrade/re-upgrade and metadata comparison passed in disposable databases; local explicit upgrade applied 0005_carrier_events; alembic check reports no drift, current is head |
| Rebuilt Compose / intake CLI | API/frontend/intake rebuilt; all five services healthy; one-off carrier-capable intake scan succeeded without registering sources or imports |
| Live HTTP verification | Both unchanged seeded roles passed login/session/bearer/revocation, area and Tracking/Search reads; direct API and Vite proxy rejected a deliberately invalid webhook key with exact 401; deployed OpenAPI exposes raw-ID route and API-key security |
| Local preservation and cleanup | integrations, carrier_receipts, ingestion_source/imports/rows, shipments, customers, area and account_mapping each contain zero rows; zero disposable p2_test_* databases remain; no real key/account/source or reference package/contact seed content provisioned |

The initial migration renderer used generic boolean output and a check-constraint drop was double-prefixed by the naming convention; both were corrected before passing real PostgreSQL upgrade/downgrade/metadata checks. Initial test/type fixture issues were corrected; the two-tenant CSV correctly created separate identically named areas. Review also fixed the process-global CSV field-limit race by keeping one parser ceiling and enforcing per-adapter bounds. Final application checks passed. One inherited Starlette TestClient/httpx deprecation warning remains. No documentation-only tests, new browser/Playwright E2E run or production performance/security certification is claimed.

P9 boundary: P8 supports delivery event/time/signer without image data. A matched new image-bearing webhook returns 503 before event/field/area effects. A CSV image-bearing new row is explicitly rejected with pod_unavailable so later valid rows continue; partial/failed archive and diagnostic rules apply. Unknown/exact-duplicate events ignore images without new work. P8 does not silently discard an accepted image, pretend to validate/resize it or create a false ready URL. P9 will add JPEG/PNG validation, preparation, image metadata/storage and independent accepted-image retries. Recorded CSV rejections do not automatically replay after P9. No production image traffic should be enabled on this intermediate slice.

Operational limits: P7's same-filesystem hard-link/immutable-final-upload requirements and bounded retries remain. Webhook body ceiling is 7,000,000 bytes; carrier CSV fields permit a 6,666,668-character envelope inside the existing 20,000,000-byte/20,000-row file bounds, while manifest fields retain 65,536 characters. Throughput/disk quota/retention and full real-backend browser E2E remain deployment/P12 work. Source registrations and integrations require explicit operator configuration; no real credentials are generated. Existing development users/passwords and all pre-existing workspace work remain preserved. P9 POD, P10 My Day/area charts, P11 export/SSE and P12 integration/performance verification are separate.

Local services remain at http://localhost:5173 and http://localhost:8000/docs. P9 is the next separate task.


## P9 results — 2026-10-27

Scope: validated/resized JPEG/PNG POD input on matched new carrier events, additive Alembic 0006_pod_images, tenant/event-linked image history and durable prepared-content queue, independent storage worker with bounded retries and trusted status/storage-only retry CLI, dummy upload adapter and current image URL selection in the existing detail DTO. Compose's optional ingestion profile now includes separate intake and pod-worker services. No new public endpoint, frontend DTO/feature, AWS SDK/account or external storage service. Approved D43/D46 and missing-image/signer rules remain unchanged; no unresolved business rule arose.

Pillow 13.0.0 was checked against official release/API documentation, pinned and locked; uv reported only the added Pillow package. JPEG/PNG content is verified and fully decoded after strict base64 and 5,000,000-byte input checks. Engineering limits are 20,000,000 decoded pixels, 20,000 maximum side and 20,000,000 prepared bytes. EXIF orientation is applied; output width caps at 900 with aspect ratio preserved/no upscale. Metadata is stripped and prepared format/dimensions/size are verified. Invalid inputs reject before event/area/field/image effects; valid CSV rows survive bad image rows. P8's temporary image-unavailable gate and its test expectations were replaced with real image validation.

Accepted events/fields and pending image rows/prepared BYTEA commit together. Prepared data is restricted PostgreSQL state, not logged or publicly served. A distinct accepted event has one image row and stable generated object key/hash. Storage retries do not reprocess events, normalize times, change receipt order or create images again. Per-image advisory locks prevent overlapping uploads; attempts/backoff commit before I/O so process crashes count toward the five-attempt bound. Failed content remains available for operator repair; ready metadata/URLs remain historical while prepared bytes are released. Diagnostic rows link image/shipment/tenant without provider exception text or raw content.

Default DummyPodStorage performs no network/upload and returns a deliberately non-downloadable https://pod.invalid/... URL. A ready row means this configured adapter returned its URL; it does not certify an actual S3 object. Future real adapters must provide idempotent object writes and bounded I/O. Detail ranks image-bearing events by event_time/receipt before readiness, preserving the prior image for missing input while refusing fallback for a newer selected pending/failed image. Late older completion cannot replace a newer image. Image readiness never invents a signer, overwrites delivery outcome or bypasses tenant/Void rules. Existing frontend image-failure handling consumes the same nullable pod_url.

Executed verification:

| Check | Actual result |
|---|---|
| Final `sh scripts/verify-p9.sh` | Passed: 271 backend tests (134 unit + 137 real PostgreSQL/Redis integration), all prior slices included |
| New P9 coverage | 46 new cases passed within the full suite: 23 preparation unit cases and 23 PostgreSQL image/worker integration cases |
| Focused image/carrier run | 74 passed, covering the new P9 tests plus 28 carrier integration regressions |
| Image validation | Actual JPEG/PNG, landscape/portrait/small/thin aspect handling, exact 5,000,000-byte boundary and over-limit rejection, strict base64/content/formats, corrupt/truncated input, pixel/side/prepared bounds, animated PNG rejection, transparency, EXIF orientation/metadata removal and parallel deterministic preparation |
| Acceptance/dedupe/ownership | Valid webhook and CSV image acceptance; invalid image/deadline full rollback; unknown/duplicate/unmatched/wrong account never prepare images; foreign detail 404 and composite event/tenant image FKs; missing signer remains incomplete, duplicate signer update remains ignored |
| Independent storage/recovery | Tracking/signer/time preserved on storage outage; respected backoff/same key/hash/prepared bytes; five-attempt exhaustion, repeated process crashes, upload/checkpoint failure, concurrent workers, permanent/checksum/URL failures and private diagnostics; trusted failed-image CLI retry updates the same image without extra events |
| Current POD | Selected pending/failed URL null with no older-image fallback; late older completion, event/receipt ties, missing-image preservation, return retention and no readiness-based status promotion |
| Ruff / formatting / strict mypy | Passed across 79 Python files |
| Standard checks in the P9 script | Backend 134 passed / 137 opt-in skipped; frontend Prettier/ESLint/TypeScript, 36 Vitest/RTL/jsdom tests, production build and direct/proxied health smoke passed |
| Migration consistency | Empty/repeated upgrade, downgrade/re-upgrade and metadata comparison passed in disposable databases; explicit local upgrade reached 0006_pod_images; alembic check reports no drift |
| Final Compose rebuild/start | API/frontend/intake/pod-worker rebuilt with the frozen dependency set; all six services healthy |
| Rebuilt worker CLI checks | Independent POD once succeeded, status returned []; file intake once also succeeded; no real sources/jobs registered |
| Live protected HTTP checks | Both unchanged seeded users passed login/cookie/bearer/revocation, area reads and Tracking/Search queries; real frontend/API/proxy/PostgreSQL/Redis readiness passed after rebuild |
| Local preservation and cleanup | Before/after: company=2, users=2; shipments/customers/area/account_mapping/integrations/ingestion_source/imports/shipment_images each remain 0; zero disposable p2_test_* databases remain |

Docker was stopped at the start; it was restarted and the dependency rebuilt without replacing private settings or resetting users. The initial autogenerated migration placed supporting composite unique keys after their dependent FKs; ordering was corrected before passing migration round trips and metadata checks. Long-string formatting and one Pillow pixel-union test annotation were corrected before final checks. One inherited Starlette TestClient/httpx deprecation warning remains. Tests use generated synthetic image bytes in disposable databases/temporary directories, never reference tenant contacts or fake placeholder image content as valid test images. No documentation-only check is counted as an application test.

POD_IMPLEMENTATION.md documents exact storage/selection/bounds/retry semantics, and DEVELOPMENT.md records staged startup/migration before optional workers. README/SPEC, API, architecture/data model, POD and carrier contracts now distinguish delivered P9 from later work. Existing workspace changes, PostgreSQL users/passwords and approved seed content remain preserved. No real key, account mapping, shipment/contact/image or AWS resource was provisioned for verification.

Limitations: dummy URLs are not downloadable objects and no real S3/public upload is claimed. Failed/pending content retention, database asset quota/backup, decoder process isolation/concurrency, deployment memory/CPU budgets, provider I/O timeouts and throughput measurements require production configuration. P8-era terminal CSV image rejections do not auto-replay after upgrade. No new real-backend browser/Playwright E2E or production security/performance certification was performed. P10 My Day/area charts, P11 export/SSE and P12 broader E2E/performance remain separate.

Local services remain at http://localhost:5173 and http://localhost:8000/docs. P10 is the next separate task.


## P10 results — 2026-10-28

Scope: PostgreSQL due-today My Day global/exception/active-area aggregates, approved statistics APIs, additive combined dashboard snapshot DTO, authenticated root My Day UI, accessible SVG status/exception charts and reuse of existing administrator area controls. Tracking continues to use full-filter metrics, sharing the same aggregate expressions without imposing My Day's due-today filter. Runtime frontend validation, refresh/error/empty/expired-session behavior and live smoke coverage were added. No dependency, schema, migration, seed, export or SSE change was required. No unresolved business rule arose; snapshot bundling, SVG implementation and refresh triggers are engineering choices documented in DASHBOARD_IMPLEMENTATION.md.

API: GET /v1/shipment-stats, /v1/exceptions-stats and /v1/area-stats are delivered with typed counts, explicit void and server report_date. The additive GET /v1/my-day bundles stats, exceptions and areas in one repeatable-read snapshot for the UI. All require verified shipper membership, reject query parameters and return no-store. The area field is preserved with a stable id; active empty areas remain present. SQL failures return sanitized 503 responses. API.md/OpenAPI specify exact final shapes.

Rules: due_date equals the PostgreSQL UTC reporting date across all assigned carriers. Total includes Void; OTP excludes it and uses strict final-time deadlines, with eligible-empty 0 and nonempty/no Delivered 100. Exceptions classify Void first, exclude Delivered and inspect one latest event across all history using event-time/receipt ordering. Consolidated/no_package/held remain literal zero. NULL/deleted-area packages remain global but have no active card; empty/all-Void card OTP is 0. Delayed carrier events/deadline corrections appear on refresh without changing original ingestion/dedupe rules.

UI: My Day replaces the root account overview. Counts, two-decimal OTP and accessible visible chart labels reconcile with server data; empty rings do not invent slices. Administrators share Add/edit/delete/restore controls; successful mutations refresh the bundle and shared options revision while retaining enabled editing until remount. Read-only users cannot mutate. Manual refresh, focus, visible-tab return and a UTC-midnight timer request server state. No last-updated/current-hour indicator or polling/SSE guarantee was added.

Executed verification:

| Check | Actual result |
|---|---|
| `API_PORT=8001 sh scripts/verify-p10.sh` | Passed: 288 backend tests (134 unit + 154 real PostgreSQL/Redis integration), all prior slices included |
| New P10 backend coverage | 17 integration cases passed: independent status/OTP matrix, strict/equal deadlines, incomplete delivery, latest history/repeats, active/empty/deleted/NULL areas, tenant-separated same names, both roles, forged/disabled membership, all four endpoint auth/error/query contracts, UTC boundary, snapshot consistency under concurrent mutation, carrier corrections/dedupe and multiple assigned carriers |
| Focused query/dashboard checks | 41 passed before the final added multi-carrier case; the final full run includes that case |
| Ruff / format / strict mypy | Passed across 83 Python files |
| Standard backend regression | 134 passed / 154 opt-in integration cases skipped in the separate standard command; opt-in cases passed in the full run above |
| Frontend Prettier / ESLint / TypeScript | Passed |
| Frontend Vitest/RTL/jsdom | 53 passed (36 existing + 17 new): DTO rejection, populated/empty/all-Void/undelivered states, errors/retry/401, accessible summaries, admin CRUD/refresh, remount reset, stale company responses, focus and UTC-midnight refresh |
| Frontend production build | Passed, Vite 7.3.7 |
| Desktop/mobile browser inspection | Synthetic built preview inspected at default desktop and 390×844: metric/chart rendering, empty/all-Void cards, zero placeholders, area editing and mobile Add dialog/focus; no horizontal page overflow at mobile width. Viewport reset and preview server stopped |
| Final Compose build/start | API/frontend/intake/pod-worker rebuilt; all six services healthy |
| Live protected smoke after rebuild | Both original seeded roles passed proxy login/session, direct bearer access, Tracking/Search/area reads, all four My Day routes and logout revocation; no credentials displayed |
| Live HTTP readiness after rebuild | Frontend, direct API, Vite proxy and real PostgreSQL/Redis health passed |
| Migration consistency | Full suite includes prior migration round trips/metadata checks; local `alembic check` reports no new operations; current remains 0006_pod_images |
| Local data/cleanup | company=2, users=2, area=2; shipments/customers/account_mapping/integrations/ingestion_source/ingestion_imports/shipment_images each 0; zero disposable p2_test_* databases remain. Existing area rows were retained; verification did not seed or mutate development business data |

Initial type/fixture/async UI test issues were corrected before the final successful suite. One inherited Starlette TestClient/httpx deprecation warning remains. Browser inspection used the app browser controls and a synthetic temporary HTTP preview; it was not a Playwright test-suite run or real-backend browser E2E. Database/API tests used real disposable PostgreSQL/Redis state; documentation checks are not counted as application tests. No throughput, production query-budget or full browser E2E certification is claimed; those remain P12. The approved standalone statistics routes currently calculate the same full report, which favors consistency over optimizing separate calls. P11 export/SSE remains the next separate slice.

During verification the Compose stack stopped. Restart encountered an unrelated fastapi-demo process already using host port 8000; that process was left running. Only ignored local .env was adjusted to API_PORT=8001 with matching allowed origins while preserving credentials/settings. The rebuilt project is running at http://localhost:5173, with API/docs at http://localhost:8001/docs. Compose reads .env; host smoke/verification commands require the explicit API_PORT=8001 prefix. Default .env.example retains port 8000. Existing work, private credentials and database volume were preserved.


## P11 results — 2026-10-28

Scope: durable PostgreSQL CSV export queue/worker, exact approved Tracking export acknowledgment, actual local CSV storage and authenticated download, requester-scoped status/recovery/dismissal APIs, authenticated SSE snapshots and Tracking/workspace export UI. Additive Alembic 0007_exports; no new dependency, seed content, external credentials/service or AWS provisioning. Shared Tracking predicates remain the source for list/metrics/export; generation streams package rows with no pagination. No unresolved business question arose. Engineering choices, exact new DTOs/paths, file publication, bounds and recovery are documented in EXPORT_IMPLEMENTATION.md.

API: GET /v1/shipments?export=1 commits verified requester/company and normalized effective dates before HTTP 202 with exactly {"message":"we start to process data"}. It rejects pagination, unknown/duplicate singleton parameters and invalid area ownership. Cookie acceptance requires the application header and an allowed supplied Origin. Added GET /v1/exports, GET /v1/exports/{UUID}, POST /v1/exports/{UUID}/dismiss, GET /v1/exports/{UUID}/download and GET /v1/exports/events. Every job/status/artifact lookup checks requester AND company, including users within one company. SSE rechecks expiry/revocation/live membership and replays current undismissed snapshots after reconnect, independently of Redis. No URL contains an access token. A 50-undismissed-job requester limit bounds recovery/state; completion dismissal is idempotent and retains audit/files.

Schema/worker: export_jobs has composite user/company ownership, normalized JSONB filters, bounded attempts/state/backoff, sanitized reason and ready file metadata (filename/size/row-count/SHA-256). PostgreSQL remains canonical. The separate optional exports profile scans due jobs, takes a per-job session lock and records attempts before I/O. Five attempts/backoff bound interruptions; ready jobs never regenerate for notification recovery. At execution, active requester membership is rechecked and packages are read in one repeatable-read snapshot. Accepted area IDs remain the predicates after later soft deletion. A PostgreSQL server cursor streams 500-row batches into a real UTF-8 CSV, with incremental hashing and a 250,000,000-byte ceiling that fails rather than truncates. Temporary fsync/atomic publish/directory fsync precede ready metadata. Unique job directories prevent same-day collisions. API mounts only sftp/download read-only; file opens reject invalid paths/symlinks/nonregular or size-mismatched output.

CSV/UI: the exact seven columns are shipment_number,carrier,route,order_date,due_date,pod_name,deliver_time. NULL is empty, zero/leading-zero strings survive, CSV quoting handles commas/quotes/newlines and formula-risk cells are prefixed without changing canonical values. Carrier/area labels and offset-aware delivery serialization reuse the normal query/time contracts; order_date is never invented. Tracking submits committed filters without page/length. Acceptance shows only the exact supplied message; pending/retry/failed states have no link. Ready notifications use Click here to download. REST and one workspace SSE stream recover after reload/focus/reconnect; validated snapshots deduplicate replay, durable dismissals survive reload and old responses are aborted across workspace changes. Desktop/mobile synthetic inspection showed the notification, link and export controls wrapping without page overflow at 390px.

Verification: the final end-to-end command completed successfully after all fixes.

| Check | Actual result |
|---|---|
| Final `API_PORT=8001 sh scripts/verify-p11.sh` | Passed end to end: 321 backend tests (145 unit + 176 real PostgreSQL/Redis integration), all standard tooling/frontend/build/HTTP checks; all prior slices included |
| New P11 backend coverage | 33 cases: 11 unit + 22 integration cases; exact/empty CSV, 13-row/no-pagination and 501-row/batch-boundary output, all status/exception/account/area/date predicates, accepted-day stability and later database rows, deleted/NULL area enrichment, quoting/formulas/leading zeros, requester/tenant/disabled membership/composite FK, concurrency/backoff/crashes/exhaustion, file limits/symlink/missing file and ready-file idempotence, exact API acknowledgment/errors/CSRF and real scoped SSE recovery |
| Focused backend run | Initial corrected export run 29 passed; initial export/database/query run 60 passed with three fixture failures, subsequently corrected; the final full suite includes the additional four integration cases |
| Ruff / format / strict mypy | Passed across 93 Python files after fixing an unused test-loop variable |
| Final frontend checks | Prettier, ESLint, TypeScript and production build passed after separating runtime DTO validation from React component exports |
| Frontend Vitest/RTL/jsdom | 67 passed: 53 existing + 14 export tests; committed-filter transport/no pagination, exact acknowledgment, duplicate-click guard, request errors/401, pending/ready/failed states, safe link validation, SSE replay/reconnect, durable dismissal and late-response abort |
| Migration | Empty/repeated upgrade, downgrade/base/re-upgrade and metadata checks included in full suite; local additive upgrade reached 0007_exports; alembic check reports no new operations |
| Final Compose build/start and post-build checks | All seven services rebuilt/healthy with final source, including export-worker; post-build HTTP health passed and all four retained CSV files were readable through the API mount with matching stored SHA-256 checksums |
| Live export smoke | Passed for both original development roles: two fresh durable jobs, actual worker CSV output, actual SSE through Vite proxy, recovery/status, requester-isolated real downloads, exact columns and dismissal; no rows/credentials displayed |
| Live auth/query/My Day smoke | Both original roles passed login/cookie/direct bearer/revocation, area reads, Tracking/Search and all My Day statistics routes after P11 |
| Synthetic browser inspection | Built UI checked at normal desktop and 390×844; readiness card/link and Export CSV render accessibly with no mobile page overflow. No production data used; preview stopped and viewport reset |
| Local preservation | company=2, users=2, area=2; shipments/customers/account_mapping remain 0. Four real empty CSV artifacts/jobs from the two smoke attempts are ready and retained, all four notifications dismissed; no tenant packages/contacts/mappings/integration credentials were seeded |
| Cleanup | One inactive disposable database left by interrupted verification was removed; final successful-run cleanup confirmed zero p2_test_* databases. No real tables/volumes reset |

Initial date fixtures incorrectly relied on the ordinary next-business-day default instead of due-today; fixture dates and the synthetic request receive channel were corrected. A rebuild interrupted the first full test process, so the run was repeated after service startup. A subsequent full suite passed 321 application tests but stopped at an unused test-variable lint check; the unused name was fixed. React Fast Refresh lint required a separate DTO module; a duplicate test import introduced during that move was then corrected. Final frontend checks passed. The first live smoke retained real output but logged out one user before its later isolation check; the script was corrected to keep both sessions active, and the rerun passed. Its leftover known notification was dismissed through the authorized API, retaining its job/file. One inherited Starlette TestClient/httpx deprecation warning remains.

No documentation-only check is counted as an application test. Browser inspection used the app's browser controls against a synthetic preview; this is not a Playwright test-suite run or full real-backend browser E2E. Real local API/worker/SSE/download behavior was separately verified over HTTP. Public S3 storage, production retention/aggregate disk quotas, temporary-file cleanup after hard crashes, timeout/CPU/memory budgets, SSE connection/proxy capacity and measured throughput remain deployment/P12 work. PostgreSQL notification polling is a two-second engineering baseline, not a production freshness/performance guarantee. P12 broader E2E/operational/performance verification remains separate.

Local services use http://localhost:5173 and http://localhost:8001/docs. Startup includes both --profile ingestion and --profile exports after the explicit migration; host verification keeps API_PORT=8001. The unrelated project on 8000 was preserved. Existing work, passwords, local settings and business data remain intact.


## P12 results — 2026-10-28

Scope: real React/Vite→FastAPI/PostgreSQL browser E2E journey against a dedicated synthetic stack; repeatable service-outage/recovery and performance harnesses; a cross-pipeline manifest/carrier/POD/dashboard/export integration test; guarded disposable fixtures; trusted read-only operator diagnostics; fixes for development API/SSE recovery. No new business decision, domain schema migration, dependency, real tenant seed content, credential reset, external account or AWS/Elasticsearch setup. Head remains 0007_exports. P12_VERIFICATION.md contains commands, exact scope, operational interpretation and deployment limits; docs/verification/p12-performance.json contains final measured data and query-plan evidence.

Isolation: compose.verification.yaml is a standalone fixed logistics-p12 project, with separate PostgreSQL/Redis/network/volume, synthetic credentials, loopback test ports and ignored .local/p12 storage. Setup/performance modules explicitly refuse non-test/non-lab databases before fixture work; an integration test verifies refusal before migrations. Benchmark databases use generated p12_perf_* names and are dropped on completion. The normal application suite retains its disposable p2_test_* database harness. Development users/passwords, existing two areas and stored export artifacts remain untouched by fixture/outage work.

Application/recovery fixes: Uvicorn now watches only /app/app and limits graceful shutdown to five seconds; test edits no longer trigger API source reload and open SSE cannot block shutdown indefinitely. Stable verification API disables source reload. SSE adds observable heartbeat events, and the client liveness watchdog checks every five seconds, renewing the stream plus REST recovery after at least 15 seconds without a frame. Two frontend regressions cover silent-stall recovery and healthy-heartbeat preservation. Existing authenticated ownership, status/acceptance/download shapes and durable ready-file behavior are unchanged. Focus/visible/manual recovery also remains; background browser throttling can delay timers.

Executed browser E2E used the app browser controls (including its Playwright locator API) against real isolated services, with no browser response mocks:

- Administrator login → My Day total 2 / undelivered 1 / OTP100 / empty and assigned area cards.
- Exact duplicate-number Search returns two seven-column rows; selecting P12-0002 opens its own reference and Undelivered detail, with leading-zero account/ZIP intact.
- Shared areas create, enable, rename, soft-delete and manual restore succeeded; reload restored the session and reset editing off.
- Export while worker stopped returned exact acceptance and pending/no link. Actual worker publication produced readiness; reload recovered it; clicking the browser link downloaded a real two-row/seven-column CSV, verified from disk without printing data.
- Administrator logout → ordinary-user login shared the same shipments/areas while hiding administrator mutation controls and all administrator export notifications. Delivered filtering reconciled one row and full-result metrics.
- Ordinary-user My Day at 390×844 had no page overflow. Browser evidence is retained in ignored .local/p12/browser-admin.jpg and browser-mobile.jpg; downloaded synthetic CSV copied to .local/p12/browser-download.csv. The browser tab was closed and viewport/visibility restored.

Executed verification:

| Check | Actual result |
|---|---|
| Final `API_PORT=8001 sh scripts/verify-p12.sh` | Passed end to end: 325 backend tests (146 unit + 179 PostgreSQL/Redis integration), standard tooling/build/HTTP checks, 69 frontend tests and trusted diagnostics |
| New cross-pipeline/diagnostic tests | 4 passed: manifest valid/rejected partial archive, carrier exact dedupe/route/image resize, independent POD and CSV storage interruptions/recovery, My Day/export reconciliation, file-content retry idempotence, requester isolation, sanitized read-only counts, outage sanitization and non-lab fixture refusal |
| Focused backend regression | 37 passed: all export tests plus the new P12 application checks |
| Focused frontend SSE regression | 16 export tests passed, including the two new liveness regressions |
| Python Ruff / formatting / strict mypy | Passed across 99 source files before final full run |
| Redis outage in isolated stack | live200 / ready503; existing session, shipment query and durable export acceptance continue; login fails closed503; recovery200 |
| PostgreSQL outage in isolated stack | live200 / ready/auth503 sanitized; restart restores same session and byte-identical ready artifact checksum |
| Export-worker/API outage in isolated stack | Pending job survives worker stop/API restart, resumes to actual two-row CSV after worker restart; readiness follows storage |
| Bounded API restart | 7.558 seconds in the first recovery run with an open browser stream; final script rerun passed with 2.600 seconds after the browser session closed |
| Final recovery script | Passed; guarded fixed test project, transient readiness resets handled, stopped test services restored in finally without image-driven recreation |
| Seed repeatability | Isolated setup ran the approved seed twice; second run created nothing or new credentials. Full suite retains prior hash/settings/concurrent-seed preservation cases |
| Final synthetic benchmark | 10,000 packages / 50,000 events / two tenants / ten areas per tenant (one deleted), 8,000 target packages, two warmups + ten samples at concurrency1; measured report retained |
| Tracking default benchmark | median348.970 ms / p95362.442 ms; 5 SQL statements per call |
| Account+area+Undelivered Tracking | median78.712 ms / p9584.727 ms; 6 SQL statements per call |
| My Day benchmark | median476.339 ms / p95499.442 ms; 5 SQL statements per call |
| Duplicate-number Search / selected-ID detail | Search median5.879 / p957.416 ms (3 statements); detail median4.229 / p956.285 ms (6 statements) |
| Streaming export benchmark | 8,000 rows / 540,073 bytes in75.283 ms for one generation; not a percentile or capacity claim |
| Benchmark environment/evidence | PostgreSQL17.6/aarch64, 10 visible CPUs; process high-water RSS includes setup/interpreter and excludes server memory. Tracking-page EXPLAIN ANALYZE/BUFFERS saved in report |

Initial P12 checks found actual API reload/SSE recovery gaps and fixed them before the final run. A diagnostic row-conversion issue and test error-column spelling were corrected; focused application checks pass. Initial type/line-length issues were corrected. A performance preparation was interrupted by isolated service recreation during the first recovery attempt; its inactive synthetic database was removed. Recovery and final benchmark were then executed sequentially, with a second benchmark after browser/outage/focused checks ended to avoid competing verification work. A recovery probe initially failed on a transient connection reset; it now tolerates transport resets while awaiting readiness and always restores the test services. The existing Starlette TestClient/httpx deprecation warning remains.

The measured baseline is warmed/local/single-client, with small shared synthetic recipient cardinality/UTC fallback and normal development services still running. It is not a production SLA, throughput/capacity proof, cold-cache/multi-client test or comprehensive workload model. Process high-water RSS is not total application/server memory or a per-operation allocation. No global PostgreSQL tuning, extra indexes/migration or Elasticsearch projection was introduced merely to improve benchmark numbers. Further deployment-equivalent measurement should drive tuning.

This is executed real-backend browser E2E plus reproducible fixtures/recovery/performance commands, not an installed unattended Playwright suite or cross-browser/accessibility certification. No documentation-only check is counted as an application test. Production storage/retention/quotas, hard-crash temporary cleanup, decoder/resource isolation, provider I/O timeouts, public S3 controls, proxy/TLS/IP/connection budgets, backups/restore drills and production capacity remain explicit deployment configuration work. P12 does not silently provision those services or claim certification.

Final full verification passed after all fixes: Ruff and format, strict mypy across 99 files, all 325 backend cases, all 69 frontend cases, Prettier/ESLint/TypeScript, production build, real frontend/API/proxy/PostgreSQL/Redis health and aggregate diagnostics. The normal separate backend unit pass had 146 passed / 179 opt-in cases skipped; the opt-in cases passed in the full run above. No dependency or migration changed. Only the inherited Starlette warning remains.

The disposable logistics-p12 containers/network/PostgreSQL volume were removed after browser/recovery/benchmark completion; ignored local screenshots/CSV/recovery reports remain. A synthetic browser download also remains in the host Downloads folder, with a verified copy under .local/p12. The final quiet benchmark auto-dropped its generated database. Post-rebuild checks passed: all seven development services healthy; both existing users passed login/session/bearer/logout, areas, Tracking/Search and My Day reads; direct/proxy readiness passed. Counts remain company=2, users=2, area=2, export_jobs=4, with shipments/customers/account_mapping/integrations/ingestion_source/ingestion_imports/shipment_images each 0. All four existing CSV checksums match; migration head is 0007_exports and zero p2_test_* databases remain. No logistics-p12 containers or volume remain. Local app/API stay at http://localhost:5173 and http://localhost:8001/docs; existing private settings and credentials are preserved.
