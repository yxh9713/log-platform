# P3 authentication contract

This document records P3 engineering choices within the approved login/security requirements. It adds session interfaces and transport without changing POST /v1/login's approved request or minimal token response. Login, session retrieval and logout are implemented; shipment/area endpoints remain later slices.

## Identity and authorization
Login normalizes email and company slug by trimming/lowercasing; password text is preserved. Required JSON fields are email (max 320), password (max 1024, nonblank), slug (max 64, nonempty). Additional fields, including role/company ID, are rejected. Login bodies are capped at 8 KiB before parsing, including chunked bodies. Validate company-scoped email/password through the shared P2 Argon2id verifier. An unknown identity still runs one password verification against a runtime dummy hash.

Only active users of active companies with company_type=2 and a recognized administrator/user role can log in. Invalid password, unknown company/email, inactive membership/company, unsupported role and carrier access all return the same 401 message. Company and role are resolved from PostgreSQL; payload/header/query selectors cannot override them.

Every protected request validates the signed token, durable session, expiry, current company membership, active user/company, shipper type and current role. Session company must equal the user's current company; a composite foreign key enforces that association. `current_user` returns the server-derived Principal; future query handlers must use Principal.company.id to scope all data. `require_administrator` enforces administrator access (403 for ordinary users) and is tested through test-only endpoints. No production administrator area operation is added in P3.

## Session design
Each login generates 32 random bytes for an opaque session ID. itsdangerous 2.2.0 signs it with HMAC-SHA256, a versioned salt and AUTH_SECRET. Tokens contain no role/company claims. PostgreSQL auth_sessions stores only the SHA-256 digest of that random ID, user/company FKs and aware creation/expiry instants. It does not store the usable bearer token. Expiry is eight hours from database transaction time, with independent signed-token age validation. No sliding extension, refresh token or remember-me behavior is provided. Expired rows cannot authenticate; retention/cleanup scheduling remains deployment work.

The returned token is usable in `Authorization: Bearer <token>`. Alternatively the server sets a host-only logistics_session cookie with Path=/v1, HttpOnly, SameSite=Strict and Max-Age=28800; Secure is required in production and disabled for local HTTP development/test. The React app uses this cookie and never writes tokens to localStorage/sessionStorage or URLs. P11 uses cookie transport for same-origin GET /v1/exports/events without exposing tokens in URLs. The stream re-authenticates on each two-second durable-state check; token expiry, revocation or disabled membership closes the stream with session-expired. See EXPORT_IMPLEMENTATION.md.

An explicit Authorization header takes precedence. A malformed/expired bearer never falls back to a valid cookie. Logout deletes the current session row, revoking that token for both cookie and bearer clients; other sessions remain independent. Invalid/expired presented tokens can still clear the browser cookie. Tokenless logout is 401. Changing AUTH_SECRET invalidates all prior signed tokens. Existing membership/role changes take effect on the next protected request. A session remains usable across application restarts when the same secret and PostgreSQL state are preserved; Redis is not session storage.

## Browser boundary and throttling
Vite proxies /v1 to the API, so browser requests stay same-origin. No cross-origin CORS access is enabled. Login requires application/json; a supplied Origin must exactly match AUTH_ALLOWED_ORIGINS. Cross-site HTML forms cannot make the approved JSON request, and cross-origin script preflights are denied. Cookie-authenticated mutations also require X-Requested-With: logistics-web plus the Origin check when present. Non-browser JSON login and bearer clients may omit Origin. Cookies use Strict same-site delivery in addition to these checks.

AUTH_ALLOWED_ORIGINS defaults to localhost/127.0.0.1 ports 5173 and 8000 for development. Set explicit HTTPS origins in production; startup rejects production HTTP origins. AUTH_SECRET is required and must contain at least 32 characters; generate 32 random bytes (e.g. openssl rand -hex 32). Settings errors hide supplied values. This is a local development stack, not a production deployment configuration.

Redis supplies atomic fixed-window login limits: 10 attempts per normalized company/email identity and 30 per source IP in 60 seconds. Successful and failed credential checks count. Keys use keyed hashes rather than raw identity/IP values, expire after 60 seconds, and are shared by API processes using the same Redis and signing key. A blocked request returns 429 and Retry-After: 60. Redis failure closes login with 503; already established sessions can still authenticate through PostgreSQL. Validation/oversized requests are rejected before credential processing. Untrusted forwarded-IP headers are disabled in the container's uvicorn command. Vite requests share the proxy's source IP; trusted proxy/IP configuration and rate-limit capacity need deployment review.

## Interfaces
All session successes/errors have Cache-Control: no-store. Error bodies contain message only; validation never reflects submitted passwords or raw database/Redis errors.

| Endpoint | Contract |
|---|---|
| POST /v1/login | JSON email/password/slug; 200 exactly {"token":"<access-token>"}, also sets session cookie |
| GET /v1/session | Cookie or bearer; 200 Principal (below) |
| POST /v1/logout | Cookie plus mutation header, or bearer; 200 {"message":"Signed out"}, revokes session and expires cookie |

Principal shape:
```json
{
  "id": "<user-id>",
  "email": "<verified-user-email>",
  "role": "administrator",
  "company": {"id": "<company-id>", "name": "<company-name>", "slug": "<company-slug>"},
  "expires_at": "<aware-UTC-ISO-8601-instant>"
}
```
Role is administrator or user. IDs in this new DTO are decimal strings to preserve PostgreSQL BIGINT values in JavaScript; this does not change existing domain DTO contracts.

| Status | Message / trigger |
|---|---|
| 401 | Invalid credentials (login); Authentication required (protected session) |
| 403 | Origin is not allowed; Request header required; Administrator role required |
| 413 | Login request is too large |
| 415 | JSON content type required |
| 422 | Check email, password and company slug. |
| 429 | Too many login attempts. Try again in one minute. |
| 503 | Authentication is temporarily unavailable |

OpenAPI declares success/error DTOs and cookie-or-bearer security on session/logout. The cookie is set automatically by login; bearer clients can use Swagger's Authorize control. The protected frontend root restores /v1/session on load/focus, expires the visible layout at expires_at, and rejects stale restore responses after logout. Loading, invalid credentials, network/service failures and throttling are visible with focused alerts/retry controls. Failed logout retains the workspace for retry rather than pretending revocation succeeded. Login fields have visible labels, native required/type validation, password masking and keyboard focus styles. The authenticated layout shows verified company/email/role; future shipment and administrator area workflows are explicitly marked as later work.
