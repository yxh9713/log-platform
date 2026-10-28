# Login

## Purpose and scope
Authenticate a shipper user for the MVP dashboard. Carrier dashboard access is deferred to phase 2; carrier integrations use separate API-key authentication.

## Form and API
Require Email, Password and Company slug. Label controls, mask password, validate missing inputs on client/server and provide useful loading/error states.

POST /v1/login:
```json
{"email":"email@example.com","password":"<password>","slug":"paychex"}
```
Successful response:
```json
{"token":"<access-token>"}
```
Invalid credentials return 401 without disclosing whether an email/company exists. Verify password hash, active company and membership. users.role_id resolves administrator/user server-side; the request cannot select a role.

## Session behavior
Protected requests must validate token/session, company membership and expiry. Token/session lifetime, refresh/logout mechanics and compatible SSE authentication are implementation security design; no MFA/remember-me/account-recovery UI is required by this feature.

Development users are provisioned by [SEED_DATA.md](../SEED_DATA.md), not a public registration endpoint. No real password is embedded in examples.

## Acceptance criteria
Reject missing/invalid input; accept valid seeded credentials; prevent cross-company login and carrier access to shipper APIs; enforce expired/missing session and role checks; support accessible keyboard/error behavior.

## Implemented P3 interfaces
P3 implements this form at the frontend root, an authenticated company/role layout and the approved POST /v1/login response. GET /v1/session and POST /v1/logout are engineering additions. Session lifetime/transport, validation errors, throttling, CSRF, revocation and SSE-compatible cookie design are specified in [AUTHENTICATION.md](../AUTHENTICATION.md). Administrator dependency enforcement is implemented and tested; actual area mutations remain their planned slice.
