# Engineering Constraints

## Required invariants
| Area | Constraint |
|---|---|
| Tenancy | Verify membership and scope every read, write, join, export and notification |
| Persistence | PostgreSQL source of truth; UTC reporting sessions; explicit Alembic migrations |
| API | Typed request/response DTOs; supplied paths/messages preserved; no unchecked ORM serialization |
| Types | Preserve identifiers/ZIP as strings; use decimal arithmetic for weight; aware normalized instants |
| Jobs | Durable acceptance, idempotent effects, bounded infrastructure retries and audit |
| UI | Keyboard-accessible controls, visible labels, responsive layout and useful failure states |
| Logging | Correlate imports/requests/jobs; redact secrets, full image payloads and unnecessary PII |
| Dependencies | Pin versions/lockfiles; avoid unrequested external services |
| Development credentials | Runtime generation or explicit local configuration; hashes in database, no committed secrets |

## Quality gates
Use formatting, type checking, unit/integration tests and feature-level verification as each slice requires. Test tenant isolation, role boundaries, concurrency and replay-sensitive business behavior. Test migrations from an empty database and the development seed command repeatedly.

## Implementation parameters
Select framework/runtime versions, queue library, database key/index design, deployment settings and precise CI commands during scaffolding. These are engineering design work, not unresolved shipment business rules. Record selected versions and runnable commands in docs/DEVELOPMENT.md.

Throughput, retention, production resource budgets and deployment targets require measurement/configuration before production. Do not claim unsupported performance or silently provision Elasticsearch/AWS.
