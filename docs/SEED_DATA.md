# Development Seed Data

## Purpose
Provide one editable, idempotent development bootstrap after schema migration. Alembic manages schema changes; a separate application seed command populates catalogs, companies and users. P2 implements this command in `backend/app/db/seed.py`, with editable declarations in `backend/app/db/seed_data.py`. See DEVELOPMENT.md for verified Compose commands and credential handling.

## Required seed records
| Entity | Required records |
|---|---|
| company | Paychex: slug paychex, company_type=2; OnTrac: slug ontrac, company_type=1 |
| user_role | administrator; user |
| shipment_actions | created; picked up; possession; out for delivery; delivered; attempted; returned |
| Paychex users | One administrator and one ordinary user, both linked to Paychex and the appropriate role |

Use existing canonical carrier spelling **OnTrac** and slug ontrac. Companies/accounts are active for local testing. Resolve foreign keys by stable slug/catalog name rather than hardcoding example IDs.

**Engineering defaults:** configurable development emails admin@paychex.example and user@paychex.example. These are development identifiers, not real contacts. No OnTrac dashboard user is required for the shipper MVP.

## Passwords
- Generate a separate strong random initial password for each newly created development user at seed execution (runtime). The owner explicitly authorizes generation for this bootstrap.
- Store only an application password hash, using the same verifier as login; never store plaintext or impose a UNIQUE password index.
- Display initial credentials once in the interactive seed command output or write to an explicitly selected private local destination. Do not write them into requirements, source files, ordinary application logs or committed fixtures.
- Rerunning seed must not reset existing passwords or repeatedly reveal credentials. Credential reset is a separate explicit operation.
- Optional local password overrides may be supported through environment/configuration without committing values. Production runs must never create development credentials automatically.

## Idempotency and customization
Keep seed declarations in an editable backend seed file/module so more companies/users can be added later. Natural identities are company slug, role/action name and user email within company. Reuse existing rows and link correct IDs; protect against concurrent duplicates in the database.

Run catalog/company/user creation transactionally. Do not delete extra manually added data, downgrade existing roles, overwrite passwords, or reset company settings on routine reruns. Report existing versus created records without exposing secrets unnecessarily.

Do not seed sample shipments, customer addresses, account_mapping values, integrations.apikey credentials, carrier accounts or real external resources. The owner will populate account mappings later.

## Command lifecycle
The target development sequence is:
```text
alembic upgrade head
python -m app.db.seed
```
These commands are runnable from `backend/` with the installed environment and database configuration. Seeding requires explicit `APP_ENV=development` and either an interactive stdout terminal or `--credentials-file` pointing to a new private file. A production migration creates schema without silently running the development seed. Required system catalogs may have a separate safe bootstrap path in deployment design.

## Acceptance criteria
- Empty migrated database receives both companies, both catalogs and two correctly scoped Paychex users.
- Generated passwords verify through the shared Argon2id verifier (`app.passwords`); P3 verifies the actual login/session flow and shared administrator guard; concrete area mutations follow their feature slice.
- Repeated and concurrent seed runs create no duplicates and never reset an existing password.
- Additional declarative company/user entries can be seeded without modifying core logic.
- No sample packages, account mappings or integration credentials are inserted.
- No generated credential is checked into source control or included in logs/test snapshots.

## P2 implementation notes
Defaults create exactly the approved records above. Edit the `SeedData` declaration to add companies/users; all referenced slugs/roles must be declared. Slugs, role/action names and email identities must already be trimmed/lowercase; malformed or duplicate declarations fail before writes. New companies/users default active. Stable natural keys and foreign keys resolve actual IDs rather than relying on sample IDs.

The seed transaction uses a PostgreSQL advisory lock and unique-key conflict handling. Existing company settings and user role/active/password/timestamp fields are preserved, even when declarations differ. A rerun does not promote or downgrade an existing user, reactivate it, reset settings or remove extra data. Initial role links apply only to newly inserted users. No explicit password override or reset command is implemented in P2.

Each new password has 24 random bytes of entropy and is hashed using Argon2id with random salt, 64 MiB memory, three iterations and parallelism four. P3 login uses the shared verifier. Hashes are not uniquely indexed. Noninteractive file mode creates a new 0600 file exclusively, refuses existing paths/symlinks, and flushes/fsyncs it before database commit. Failed writes roll back the transaction. If commit fails after the file is prepared, the private file is retained so potentially committed credentials are not lost; verify database state before retrying. Files are never overwritten by reruns, which produce an empty `users` array at a new destination if nothing is created.

Console credentials are shown only after successful commit and only to an interactive terminal. Output delivery is not atomic with commit: a process/terminal failure after commit can prevent display; use private-file mode when credential preservation matters. No production safety is inferred from the presence of a file: running seed against a target database remains an explicit operator action requiring `APP_ENV=development`.
